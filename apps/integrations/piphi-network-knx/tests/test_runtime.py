from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from piphi_network_knx.main import app
from piphi_network_knx.protocol import KnxNotSentError
from piphi_network_knx.state import get_entry_or_404, manager

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
        assert entities[0]["state"]["available"] is True
        manager.sessions["office"].updated_at["light"] = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()
        assert (await client.get("/entities")).json()["entities"][0]["state"]["quality"] == "stale"

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

        missing_datapoint = await client.post(
            "/command",
            json={
                "command": "read_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "missing"},
            },
        )
        assert missing_datapoint.json()["status"] == "failed"
        missing_value = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "light"},
            },
        )
        assert missing_value.json()["status"] == "failed"
        read_only_write = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "temperature", "value": 20},
            },
        )
        assert read_only_write.json()["status"] == "failed"
        assert get_entry_or_404("office")["config_id"] == "office"

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

        fake.fail_write = KnxNotSentError("queue is full")
        rejected = await client.post(
            "/command",
            json={
                "command": "write_datapoint",
                "config_id": "office",
                "params": {"datapoint_id": "light", "value": True},
            },
        )
        assert rejected.json()["status"] == "failed"
        events = (await client.get("/events")).json()["events"]
        rejected_event = next(
            item for item in events if item["event_type"] == "telegram.write_rejected"
        )
        assert rejected_event["payload"]["outcome"] == "not_sent"

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
        entities = (await client.get("/entities")).json()["entities"]
        assert entities[0]["state"]["available"] is False
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


@pytest.mark.anyio
async def test_endpoint_reservation_blocks_concurrent_duplicate_config(fake_knx) -> None:
    fake_knx.start_gate = asyncio.Event()
    fake_knx.start_entered = asyncio.Event()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = asyncio.create_task(client.post("/config", json=CONFIG))
        await fake_knx.start_entered.wait()
        duplicate = await client.post("/config", json={**CONFIG, "id": "duplicate"})
        assert duplicate.status_code == 409
        fake_knx.start_gate.set()
        assert (await first).status_code == 200
        assert set(manager.sessions) == {"office"}


@pytest.mark.anyio
async def test_persistence_failure_preserves_working_config(fake_knx, monkeypatch) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/config", json=CONFIG)).status_code == 200
        original = manager.sessions["office"]

        def fail_persistence(_configs) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(manager, "_persist_configs", fail_persistence)
        changed = await client.post("/config", json={**CONFIG, "host": "192.0.2.11"})
        assert changed.status_code == 500
        assert manager.sessions["office"] is original
        assert fake_knx.instances[-1].connected is False

        removed = await client.post("/deconfigure/office")
        assert removed.status_code == 500
        assert manager.sessions["office"] is original


@pytest.mark.anyio
async def test_operational_responses_do_not_expose_network_or_group_addresses(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json=CONFIG)
        for path in ("/health", "/diagnostics", "/state", "/entities", "/events"):
            response = await client.get(path)
            response_text = response.text
            assert CONFIG["host"] not in response_text
            assert "1/2/3" not in response_text
            assert "1/2/4" not in response_text
            assert "1/3/1" not in response_text
            if path == "/health":
                assert "active_configs" not in response_text
                assert response.json()["metadata"] == {"scope": "liveness"}
