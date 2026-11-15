from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueRead

import piphi_network_knx.lifecycle as lifecycle
import piphi_network_knx.protocol as protocol
import piphi_network_knx.routes.discovery as discovery_routes
from piphi_network_knx.main import app
from piphi_network_knx.protocol import KnxNotSentError, XknxClient
from piphi_network_knx.schemas import DeviceConfig
from piphi_network_knx.settings import DEFAULT_PORT, runtime_port
from piphi_network_knx.state import manager

CONFIG = {
    "id": "office",
    "host": "192.0.2.10",
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


@pytest.mark.parametrize(
    "datapoint",
    [
        {
            "id": "bad",
            "name": "Bad",
            "entity_type": "switch",
            "dpt": "1.001",
            "state_address": "1/2",
        },
        {
            "id": "bad",
            "name": "Bad",
            "entity_type": "switch",
            "dpt": "1.001",
            "state_address": "a/b/c",
        },
        {
            "id": "bad",
            "name": "Bad",
            "entity_type": "sensor",
            "dpt": "9.001",
            "state_address": "1/2/3",
            "command_address": "1/2/4",
            "writable": True,
        },
        {
            "id": "bad",
            "name": "Bad",
            "entity_type": "switch",
            "dpt": "1.001",
            "state_address": "1/2/3",
            "writable": True,
        },
        {
            "id": "bad",
            "name": "Bad",
            "entity_type": "switch",
            "dpt": "1.001",
            "state_address": "1/2/3",
            "command_address": "1/2/4",
        },
    ],
)
def test_additional_invalid_datapoint_shapes_fail_closed(datapoint) -> None:
    with pytest.raises(ValidationError):
        DeviceConfig.model_validate(
            {"id": "test", "host": "192.0.2.1", "allow_writes": True, "datapoints": [datapoint]}
        )


def test_duplicate_datapoints_and_invalid_runtime_port_fail_closed(monkeypatch) -> None:
    duplicate = {**CONFIG, "datapoints": [CONFIG["datapoints"][0], CONFIG["datapoints"][0]]}
    with pytest.raises(ValidationError):
        DeviceConfig.model_validate(duplicate)
    duplicate_address = {
        **CONFIG,
        "datapoints": [
            CONFIG["datapoints"][0],
            {**CONFIG["datapoints"][1], "state_address": "1/2/3"},
        ],
    }
    with pytest.raises(ValidationError):
        DeviceConfig.model_validate(duplicate_address)
    monkeypatch.setenv("PORT", "not-a-port")
    assert runtime_port() == DEFAULT_PORT
    monkeypatch.setenv("PORT", "5000")
    assert runtime_port() == 5000


@pytest.mark.anyio
async def test_command_and_deconfigure_validation_errors(fake_knx) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.post("/command", json={})).status_code == 400
        missing_config = await client.post("/command", json={"command": "read_datapoint"})
        assert missing_config.status_code == 400
        unsupported = await client.post(
            "/command",
            json={
                "command": "read_datapoint",
                "config_id": "missing",
                "capability": "write_datapoint",
            },
        )
        assert unsupported.status_code == 400
        assert (await client.post("/deconfigure", json={})).json()["reason"] == "missing config_id"
        assert (await client.post("/deconfigure/missing")).status_code == 200


@pytest.mark.anyio
async def test_discovery_success_and_failure(monkeypatch) -> None:
    async def successful_discovery(local_ip):
        assert local_ip == "192.0.2.2"
        return [{"id": "gateway", "device_id": "gateway", "host": "192.0.2.3"}]

    monkeypatch.setattr(discovery_routes, "discover_gateways", successful_discovery)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/discover", json={"inputs": {"local_ip": "192.0.2.2"}})
        assert response.status_code == 200
        assert response.json()["devices"][0]["id"] == "gateway"

        async def failed_discovery(_local_ip):
            raise OSError("network unavailable")

        monkeypatch.setattr(discovery_routes, "discover_gateways", failed_discovery)
        assert (await client.post("/discover", json={})).status_code == 503


@pytest.mark.anyio
async def test_lifecycle_restores_and_stops_sessions(monkeypatch) -> None:
    restore = AsyncMock()
    stop_all = AsyncMock()
    monkeypatch.setattr(manager, "restore", restore)
    monkeypatch.setattr(manager, "stop_all", stop_all)

    @asynccontextmanager
    async def fake_runtime_lifespan(_runtime, *, on_startup):
        await on_startup(None, None)
        yield

    monkeypatch.setattr(lifecycle, "runtime_lifespan", fake_runtime_lifespan)
    async with lifecycle.lifespan(FastAPI()):
        restore.assert_awaited_once()
    stop_all.assert_awaited_once()


@pytest.mark.anyio
async def test_restore_ignores_invalid_persistence_and_unknown_config_is_404(fake_knx) -> None:
    manager.persistence_path.write_text("not-json", encoding="utf-8")
    await manager.restore()
    assert not manager.sessions
    with pytest.raises(Exception) as exc_info:
        manager.get("missing")
    assert getattr(exc_info.value, "status_code", None) == 404


@pytest.mark.anyio
async def test_cancelled_candidate_releases_endpoint_reservation(fake_knx) -> None:
    fake_knx.start_gate = asyncio.Event()
    fake_knx.start_entered = asyncio.Event()
    config = DeviceConfig.model_validate(CONFIG)
    apply_task = asyncio.create_task(manager.apply(config))
    await fake_knx.start_entered.wait()
    apply_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await apply_task
    assert not manager._pending_endpoints
    assert fake_knx.instances[0].connected is False


@pytest.mark.anyio
async def test_adapter_rejects_disconnected_send_and_ignores_unmapped_telegram(monkeypatch) -> None:
    class DisconnectedXknx:
        def __init__(self, **_kwargs) -> None:
            self.connection_manager = SimpleNamespace(connected=asyncio.Event())
            self.telegram_queue = SimpleNamespace(process_telegram_outgoing=AsyncMock())
            self.stopped = False

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(protocol, "XKNX", DisconnectedXknx)
    config = DeviceConfig.model_validate(
        {"id": "test", "host": "192.0.2.1", "datapoints": CONFIG["datapoints"][1:]}
    )
    client = XknxClient(config, lambda *_: None, lambda *_: None)
    with pytest.raises(ConnectionError):
        await client.start()
    assert client._xknx.stopped is True
    with pytest.raises(KnxNotSentError):
        await client.read(config.datapoints[0])
    client._telegram_received(Telegram(GroupAddress("2/2/2"), payload=GroupValueRead()))
