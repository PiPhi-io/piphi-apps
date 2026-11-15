from __future__ import annotations

import httpx
import pytest

from piphi_network_knx.main import app
from piphi_network_knx.state import manager

CONFIG = {
    "id": "office",
    "host": "192.0.2.10",
    "alias": "Office",
    "allow_writes": True,
    "datapoints": [
        {
            "id": "light",
            "name": "Office light",
            "entity_type": "light",
            "dpt": "1.001",
            "state_address": "1/2/3",
            "command_address": "1/2/4",
            "writable": True,
        },
        {
            "id": "temperature",
            "name": "Office temperature",
            "entity_type": "sensor",
            "dpt": "9.001",
            "state_address": "1/3/1",
        },
    ],
}


@pytest.mark.anyio
async def test_config_entities_feedback_reads_writes_and_persistence(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/config", json=CONFIG)
        assert response.status_code == 200
        fake = fake_knx.instances[0]
        assert fake.reads == ["light", "temperature"]
        assert manager.persistence_path.stat().st_mode & 0o777 == 0o600

        entities = (await client.get("/entities")).json()["entities"]
        assert len(entities) == 2
        assert entities[0]["state"]["quality"] == "uninitialized"

        fake.receive("light", True)
        entities = (await client.get("/entities")).json()["entities"]
        assert entities[0]["state"]["value"] is True

        write = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "light", "value": False},
            },
        )
        assert write.status_code == 200
        assert write.json()["feedback_pending"] is True
        assert fake.writes == [("light", False)]

        read = await client.post(
            "/command",
            json={
                "command": "read_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "temperature"},
            },
        )
        assert read.status_code == 200
        assert fake.reads[-1] == "temperature"

        assert (await client.post("/deconfigure/office")).status_code == 200


@pytest.mark.anyio
async def test_write_validation_unknown_outcome_and_disconnect_event(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json=CONFIG)
        fake = fake_knx.instances[0]
        invalid = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "light", "value": 1},
            },
        )
        assert invalid.status_code == 200
        assert invalid.json()["status"] == "failed"

        fake.fail_write = TimeoutError("confirmation timeout")
        unknown = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "light", "value": True},
            },
        )
        assert unknown.status_code == 200
        assert unknown.json()["status"] == "failed"
        fake.disconnect()
        events = (await client.get("/events")).json()["events"]
        assert any(item["event_type"] == "gateway.offline" for item in events)


@pytest.mark.anyio
async def test_runtime_token_protects_operational_routes(fake_knx, monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED")
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 401
        assert (
            await client.get("/entities", headers={"X-PiPhi-Integration-Token": "secret"})
        ).status_code == 200


@pytest.mark.anyio
async def test_missing_runtime_token_fails_closed(fake_knx, monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 503


@pytest.mark.anyio
async def test_diagnostics_state_and_restore(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json=CONFIG)
        assert (await client.get("/diagnostics")).json()["diagnostics"]["sessions"][0]["connected"]
        assert (await client.get("/state")).json()["summary"]["active_config_count"] == 1
        await manager.stop_all()
        for config_id in list(manager.sessions):
            await manager.remove(config_id, persist=False)
        manager.sessions.clear()
        from piphi_network_knx.state import registry

        registry.remove("office")
        await manager.restore()
        assert "office" in manager.sessions


@pytest.mark.anyio
async def test_reconfigure_is_atomic_and_duplicate_endpoint_is_rejected(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/config", json=CONFIG)).status_code == 200
        original = manager.sessions["office"].client

        fake_knx.fail_next_start = True
        changed = {**CONFIG, "host": "192.0.2.11"}
        failed = await client.post("/config", json=changed)
        assert failed.status_code == 422
        assert manager.sessions["office"].client is original

        duplicate = {**CONFIG, "id": "duplicate"}
        conflict = await client.post("/config", json=duplicate)
        assert conflict.status_code == 409
        assert set(manager.sessions) == {"office"}


@pytest.mark.anyio
async def test_config_snapshot_sync_removes_stale_configs(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json=CONFIG)
        sync = await client.post(
            "/config/sync",
            json={"container_id": "test-container", "generation": 2, "configs": []},
        )
        assert sync.status_code == 200
        assert not manager.sessions
