from __future__ import annotations

from typing import Any

import httpx
import pytest

from piphi_network_modbus import state
from piphi_network_modbus.main import app
from piphi_network_modbus.schemas import DeviceConfig
from piphi_network_modbus.state import runtime


class FakeSidecarClient:
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.value: float = 21.5
        self.calls: list[tuple[str, Any]] = []
        self.stream_id = "stream-1"
        self.events_payload: dict[str, Any] = {
            "events": [],
            "next_cursor": 0,
            "stream_id": self.stream_id,
            "gap": False,
            "dropped": 0,
        }

    async def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.config = payload
        self.calls.append(("configure", payload))
        return {"ok": True}

    async def snapshot(self, config_id: str) -> dict[str, Any]:
        self.calls.append(("snapshot", config_id))
        return {
            "schema_version": "piphi.modbus.snapshot.v1",
            "config_id": config_id,
            "connected": True,
            "port_open": True,
            "responsive_unit_ids": [1],
            "profile_id": "acme.meter",
            "profile_version": "1.0.0",
            "profile_hash": "abc123",
            "queue_depth": 0,
            "queue_capacity": 100,
            "last_error_code": None,
            "stream_id": self.stream_id,
            "latest_sequence": 0,
            "dropped_event_count": 0,
            "points": [
                {
                    "id": "temperature",
                    "name": "Temperature",
                    "unit_id": 1,
                    "area": "holding_register",
                    "address": 10,
                    "data_type": "int16",
                    "byte_order": "ABCD",
                    "unit": "°C",
                    "writable": True,
                    "minimum": -40,
                    "maximum": 125,
                    "value": self.value,
                    "quality": "good",
                    "updated_at": "2026-11-13T00:00:00Z",
                }
            ],
        }

    async def refresh(self, config_id: str, point_id: str | None = None) -> dict[str, Any]:
        self.calls.append(("refresh", (config_id, point_id)))
        return await self.snapshot(config_id)

    async def events(self, config_id: str, *, after: int, limit: int = 500) -> dict[str, Any]:
        self.calls.append(("events", (config_id, after, limit)))
        return self.events_payload

    async def write(self, config_id: str, point_id: str, value: Any) -> dict[str, Any]:
        self.calls.append(("write", (config_id, point_id, value)))
        self.value = float(value)
        return {"ok": True, "value": self.value}


def rtu_config(config_id: str = "rtu-parent") -> DeviceConfig:
    return DeviceConfig.model_validate(
        {
            "id": config_id,
            "host": "modbus-rtu-sidecar",
            "transport": "rtu_sidecar",
            "serial_port": "/dev/serial/by-id/private",
            "profile_id": "acme.meter",
            "profile_version": "1.0.0",
            "points": [
                {
                    "id": "temperature",
                    "name": "Temperature",
                    "unit_id": 1,
                    "address": 10,
                    "data_type": "int16",
                    "unit": "°C",
                    "scale": 0.1,
                    "writable": True,
                    "minimum": -40,
                    "maximum": 125,
                }
            ],
        }
    )


def test_parent_rejects_overlapping_profile_points() -> None:
    payload = rtu_config().model_dump()
    payload["points"].append(
        {
            "id": "duplicate_range",
            "name": "Duplicate range",
            "unit_id": 1,
            "address": 10,
            "data_type": "uint16",
        }
    )
    with pytest.raises(ValueError, match="address ranges must not overlap"):
        DeviceConfig.model_validate(payload)


@pytest.mark.anyio
async def test_parent_configures_sidecar_and_creates_metadata_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSidecarClient()
    monkeypatch.setattr(state, "sidecar_client_factory", lambda: client)
    await state.apply_config(rtu_config())
    transport = httpx.ASGITransport(app=app)
    try:
        assert client.config["registers"][0]["id"] == "temperature"
        assert "points" not in client.config
        async with httpx.AsyncClient(transport=transport, base_url="http://parent") as http:
            entities = (await http.get("/entities")).json()["entities"]
        entity = next(item for item in entities if item["id"] == "rtu-parent:temperature")
        assert entity["entity_type"] == "sensor"
        assert entity["state"]["point_value"] == pytest.approx(21.5)
        assert entity["state"]["quality"] == "good"
        assert entity["metadata"]["writable"] is True
        assert {item["id"] for item in entity["available_commands"]} == {
            "refresh",
            "set_value",
        }
    finally:
        await state.remove_config("rtu-parent")


@pytest.mark.anyio
async def test_parent_write_uses_only_resolved_profile_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSidecarClient()
    monkeypatch.setattr(state, "sidecar_client_factory", lambda: client)
    await state.apply_config(rtu_config("write-parent"))
    try:
        await state.execute_sidecar_command(
            config_id="write-parent",
            device_id="write-parent:temperature",
            command="set_value",
            args={"value": 22.0, "address": 999, "unit_id": 247},
        )
        assert ("write", ("write-parent", "temperature", 22.0)) in client.calls
        assert state.point_models["write-parent"][0]["state"]["point_value"] == 22.0
        with pytest.raises(ValueError, match="unknown_modbus_point"):
            await state.execute_sidecar_command(
                config_id="write-parent",
                device_id="write-parent:unknown",
                command="set_value",
                args={"value": 1},
            )
    finally:
        await state.remove_config("write-parent")


@pytest.mark.anyio
async def test_parent_replays_events_and_resynchronizes_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeSidecarClient()
    monkeypatch.setattr(state, "sidecar_client_factory", lambda: client)
    await state.apply_config(rtu_config("replay-parent"))
    entry = state.registry.get("replay-parent")
    assert entry is not None
    try:
        client.events_payload = {
            "events": [
                {
                    "sequence": 1,
                    "event_type": "point.changed",
                    "payload": {"point_id": "temperature", "value": 22.0},
                }
            ],
            "next_cursor": 1,
            "stream_id": "stream-1",
            "gap": False,
            "dropped": 0,
        }
        await state.replay_sidecar_events(entry, client)
        assert state.sidecar_replay["replay-parent"]["cursor"] == 1
        assert any(
            event["event_type"] == "point.changed"
            for event in state.registry.recent_events
        )

        client.stream_id = "stream-2"
        client.events_payload = {
            "events": [],
            "next_cursor": 0,
            "stream_id": "stream-2",
            "gap": False,
            "dropped": 0,
        }
        await state.replay_sidecar_events(entry, client)
        assert state.sidecar_replay["replay-parent"]["stream_id"] == "stream-2"
        assert any(
            event["event_type"] == "modbus.events.resynchronized"
            and event["payload"]["reason"] == "sidecar_restart"
            for event in state.registry.recent_events
        )
    finally:
        await state.remove_config("replay-parent")


@pytest.mark.anyio
async def test_production_mutations_fail_closed_without_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    runtime.auth.container_id = ""
    runtime.auth.internal_token = ""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://parent") as client:
        command = await client.post(
            "/command", json={"command": "refresh", "target": {"config_id": "missing"}}
        )
        deconfigure = await client.post("/deconfigure/missing")
    assert command.status_code == 503
    assert deconfigure.status_code == 503
