from __future__ import annotations

import asyncio
import httpx
import pytest
from uuid import uuid4

from piphi_network_zwave import state as runtime_state
from piphi_network_zwave.main import app
from piphi_network_zwave.sidecar_client import SidecarError
from piphi_network_zwave.state import runtime

from conftest import FakeSidecarClient


class RecoveringSidecarClient(FakeSidecarClient):
    failures_remaining = 1

    async def snapshot(self):
        if type(self).failures_remaining:
            type(self).failures_remaining -= 1
            raise SidecarError("temporarily unavailable")
        return await super().snapshot()


class GapSidecarClient(FakeSidecarClient):
    async def events(self, *, after: int, limit: int = 500):
        replay = await super().events(after=after, limit=limit)
        replay["gap"] = True
        replay["first_sequence"] = after + 2
        return replay


@pytest.mark.anyio
async def test_snapshot_creates_real_metadata_negotiated_entities() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            response = await client.post(
                "/config", json={"id": "home-network", "alias": "Home Z-Wave"}
            )
            assert response.status_code == 200

            entities = (await client.get("/entities")).json()["entities"]
            kitchen = next(entity for entity in entities if entity["device_id"] == "zwave-node-2-endpoint-0")
            hall = next(entity for entity in entities if entity["device_id"] == "zwave-node-5-endpoint-0")

            assert kitchen["entity_type"] == "switch"
            assert {"switch_state", "power_w"} <= set(kitchen["capabilities"])
            assert "set_switch" in {command["id"] for command in kitchen["available_commands"]}
            assert kitchen["metadata"]["manufacturer_id"] == 900
            assert {"temperature_c", "battery_percent"} <= set(hall["capabilities"])

            state = (await client.get("/state")).json()
            snapshot = state["entries"]["home-network"]["latest_state"]
            assert snapshot["connected"] is True
            assert snapshot["nodes"]["zwave-node-2-endpoint-0"]["power_w"] == 46.7
            assert snapshot["nodes"]["zwave-node-5-endpoint-0"]["temperature_c"] == 22.1

            discovery = (await client.post("/discover", json={})).json()["devices"]
            assert discovery[0]["network_id"] == "primary"
            assert discovery[0]["node_count"] == 2
        finally:
            await client.post("/deconfigure/home-network")


@pytest.mark.anyio
async def test_commands_require_the_bound_runtime_identity() -> None:
    runtime.auth.update(container_id="owner-container", internal_token="owner-token")
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            denied = await client.post(
                "/command",
                json={"command": "refresh", "target": {"config_id": "missing", "device_id": "missing"}},
            )
            assert denied.status_code == 401

            authorized = await client.post(
                "/command",
                headers={
                    "X-Container-Id": "owner-container",
                    "X-PiPhi-Integration-Token": "owner-token",
                    "X-PiPhi-Idempotency-Key": f"authorized-{uuid4()}",
                },
                json={"command": "refresh", "target": {"config_id": "missing", "device_id": "missing"}},
            )
            assert authorized.status_code == 200
            assert authorized.json()["status"] == "failed"
    finally:
        runtime.auth.container_id = ""
        runtime.auth.internal_token = ""


@pytest.mark.anyio
async def test_set_switch_resolves_only_advertised_writable_value() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            await client.post("/config", json={"id": "home-network"})
            response = await client.post(
                "/command",
                headers={"X-PiPhi-Idempotency-Key": f"switch-on-{uuid4()}"},
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "set_switch",
                    "target": {
                        "config_id": "home-network",
                        "device_id": "zwave-node-2-endpoint-0",
                    },
                    "params": {"value": True},
                    "capability": "action.set_switch",
                },
            )
            assert response.status_code == 200, response.text
            call = FakeSidecarClient.commands[-1]
            assert call["command"] == "set_value"
            assert call["params"] == {
                "node_id": 2,
                "value_id": {
                    "command_class": 37,
                    "endpoint": 0,
                    "property": "targetValue",
                },
                "value": True,
            }
            current = (await client.get("/state")).json()["entries"]["home-network"]
            assert (
                current["latest_state"]["nodes"]["zwave-node-2-endpoint-0"]["switch_state"]
                is False
            )
        finally:
            await client.post("/deconfigure/home-network")


@pytest.mark.anyio
async def test_set_switch_fails_closed_for_non_switch_entity() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            await client.post("/config", json={"id": "home-network"})
            response = await client.post(
                "/command",
                headers={"X-PiPhi-Idempotency-Key": f"unsafe-switch-{uuid4()}"},
                json={
                    "command": "set_switch",
                    "target": {
                        "config_id": "home-network",
                        "device_id": "zwave-node-5-endpoint-0",
                    },
                    "params": {"value": True},
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "failed"
            assert body["error"] == "capability_is_not_writeable"
            assert not FakeSidecarClient.commands
        finally:
            await client.post("/deconfigure/home-network")


@pytest.mark.anyio
async def test_supervisor_recovers_after_initial_sidecar_unavailability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecoveringSidecarClient.reset()
    RecoveringSidecarClient.failures_remaining = 1
    monkeypatch.setattr(runtime_state, "client_factory", RecoveringSidecarClient)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            response = await client.post(
                "/config",
                json={
                    "id": "recovering-network",
                    "event_poll_interval_seconds": 0.25,
                },
            )
            assert response.status_code == 200
            await asyncio.sleep(0.05)
            current = (await client.get("/state")).json()["entries"]["recovering-network"]
            assert current["latest_state"]["connected"] is True
            assert RecoveringSidecarClient.snapshot_calls >= 1
        finally:
            await client.post("/deconfigure/recovering-network")


@pytest.mark.anyio
async def test_replay_gap_forces_snapshot_resynchronization_without_skipping_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    GapSidecarClient.reset()
    monkeypatch.setattr(runtime_state, "client_factory", GapSidecarClient)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            await client.post(
                "/config",
                json={"id": "gap-network", "event_poll_interval_seconds": 0.25},
            )
            await asyncio.sleep(0.05)
            assert GapSidecarClient.snapshot_calls >= 2
            event_types = {
                event["event_type"] for event in (await client.get("/events")).json()["events"]
            }
            assert "zwave.events.resynchronized" in event_types

            supervisor = runtime_state.supervisors["gap-network"]
            supervisor.cursor = 2
            supervisor.stream_id = "stream-test-1"
            await supervisor.sync_snapshot(reason="poll", advance_cursor=False)
            assert supervisor.cursor == 2
        finally:
            await client.post("/deconfigure/gap-network")
