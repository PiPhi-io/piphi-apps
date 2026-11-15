from __future__ import annotations

from typing import Any

import httpx
import pytest

from piphi_modbus_rtu_sidecar import state
from piphi_modbus_rtu_sidecar.main import app
from piphi_modbus_rtu_sidecar.transport import BoundedQueue


class FakeSession:
    def __init__(self, _config) -> None:
        self.queue = BoundedQueue(10)
        self.values: dict[tuple[int, int], list[int | bool]] = {(1, 10): [215]}
        self.opened = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False

    async def read(self, point) -> list[int | bool]:
        return self.values.get(
            (point.unit_id, point.address), [False] if point.area == "coil" else [0]
        )

    async def write(self, point, values: list[int | bool]) -> None:
        self.values[(point.unit_id, point.address)] = values

    async def write_coils(self, points, values: list[bool]) -> None:
        for point, value in zip(points, values, strict=True):
            self.values[(point.unit_id, point.address)] = [value]


def config_payload(config_id: str = "api-test") -> dict[str, Any]:
    return {
        "id": config_id,
        "host": "modbus-rtu-sidecar",
        "serial_port": "/dev/serial/by-id/never-exposed",
        "profile_id": "acme.meter",
        "profile_version": "1.0.0",
        "profile_provenance": "Acme manual revision 4",
        "registers": [
            {
                "id": "temperature",
                "name": "Temperature",
                "unit_id": 1,
                "address": 10,
                "data_type": "int16",
                "unit": "°C",
                "scale": 0.1,
                "minimum": -40,
                "maximum": 125,
                "writable": True,
            }
        ],
    }


def coil_config_payload() -> dict[str, Any]:
    payload = config_payload("coil-api")
    payload["registers"] = [
        {
            "id": f"relay_{index}",
            "name": f"Relay {index}",
            "unit_id": 1,
            "area": "coil",
            "address": index,
            "data_type": "bool",
            "writable": True,
        }
        for index in range(3)
    ]
    return payload


@pytest.mark.anyio
async def test_authenticated_snapshot_refresh_and_constrained_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "session_factory", FakeSession)
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", "internal")
    headers = {"Authorization": "Bearer internal"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        try:
            configured = await client.post("/config", json=config_payload(), headers=headers)
            assert configured.status_code == 200

            denied = await client.get("/v1/modbus/snapshot?config_id=api-test")
            assert denied.status_code == 401
            snapshot = (
                await client.get(
                    "/v1/modbus/snapshot?config_id=api-test", headers=headers
                )
            ).json()
            assert snapshot["schema_version"] == "piphi.modbus.snapshot.v1"
            assert snapshot["connected"] is True
            assert snapshot["profile_id"] == "acme.meter"
            assert snapshot["points"][0]["value"] == pytest.approx(21.5)
            assert snapshot["request_success_count"] == 1
            assert snapshot["request_failure_count"] == 0
            assert snapshot["unit_health"][0]["last_success_at"]
            assert snapshot["poll_duration_ms"] >= 0
            assert "never-exposed" not in str(snapshot)

            written = await client.post(
                "/v1/modbus/write",
                headers=headers,
                json={"config_id": "api-test", "point_id": "temperature", "value": 22.0},
            )
            assert written.status_code == 200
            assert written.json()["value"] == pytest.approx(22.0)

            override = await client.post(
                "/v1/modbus/write",
                headers=headers,
                json={
                    "point_id": "temperature",
                    "config_id": "api-test",
                    "value": 22.0,
                    "address": 11,
                    "unit_id": 2,
                    "function": 16,
                },
            )
            assert override.status_code == 400
            controller = state.get_controller("api-test")
            assert controller.session.values == {(1, 10): [220]}

            rejected = await client.post(
                "/v1/modbus/write",
                headers=headers,
                json={"config_id": "api-test", "point_id": "temperature", "value": 126},
            )
            assert rejected.status_code == 400
            assert "above_maximum" in rejected.text

            async def timeout_read(_point):
                raise TimeoutError("modbus_response_timeout")

            monkeypatch.setattr(controller.session, "read", timeout_read)
            refreshed = await client.post(
                "/v1/modbus/refresh",
                headers=headers,
                json={"config_id": "api-test", "point_id": "temperature"},
            )
            assert refreshed.status_code == 200
            failed_snapshot = (
                await client.get(
                    "/v1/modbus/snapshot?config_id=api-test", headers=headers
                )
            ).json()
            assert failed_snapshot["timeout_count"] == 1
            assert failed_snapshot["request_failure_count"] == 1
            assert failed_snapshot["unit_health"][0]["consecutive_error_count"] == 1
        finally:
            await client.post("/deconfigure/api-test", headers=headers)


@pytest.mark.anyio
async def test_authenticated_fc15_binding_rejects_transport_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "session_factory", FakeSession)
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", "internal")
    headers = {"Authorization": "Bearer internal"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        try:
            configured = await client.post(
                "/config", json=coil_config_payload(), headers=headers
            )
            assert configured.status_code == 200
            written = await client.post(
                "/v1/modbus/write-coils",
                headers=headers,
                json={
                    "config_id": "coil-api",
                    "point_ids": ["relay_0", "relay_1", "relay_2"],
                    "values": [True, False, True],
                },
            )
            assert written.status_code == 200
            assert written.json()["values"] == [True, False, True]
            rejected = await client.post(
                "/v1/modbus/write-coils",
                headers=headers,
                json={
                    "config_id": "coil-api",
                    "point_ids": ["relay_0", "relay_1"],
                    "values": [True, True],
                    "address": 500,
                },
            )
            assert rejected.status_code == 400
        finally:
            await client.post("/deconfigure/coil-api", headers=headers)


@pytest.mark.anyio
async def test_failed_reconfiguration_preserves_working_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(state, "session_factory", FakeSession)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://sidecar") as client:
        try:
            assert (await client.post("/config", json=config_payload("transactional"))).status_code == 200
            original = state.get_controller("transactional")

            class FailedSession(FakeSession):
                async def open(self) -> None:
                    raise OSError("port busy")

            monkeypatch.setattr(state, "session_factory", FailedSession)
            with pytest.raises(ValueError, match="previous_session_preserved"):
                await state.apply_config(
                    state.DeviceConfig.model_validate(config_payload("transactional"))
                )
            assert state.get_controller("transactional") is original
            assert original.session.opened is True
        finally:
            await client.post("/deconfigure/transactional")
