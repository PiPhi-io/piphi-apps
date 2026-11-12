from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path

import httpx
import pytest

from piphi_network_modbus import state
from piphi_network_modbus.main import app
from piphi_network_modbus.modbus_tcp import (
    HoldingRegister,
    _tcp_endpoint,
    read_holding_register,
)
from piphi_network_modbus.schemas import DeviceConfig


class FakeWriter:
    def __init__(self) -> None:
        self.request = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.request += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.anyio
async def test_reads_only_configured_holding_register(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">HHHB", 1, 0, 5, 7) + bytes([3, 2, 0x12, 0x34]))
    reader.feed_eof()
    writer = FakeWriter()

    async def connect(host: str, port: int):
        assert (host, port) == ("127.0.0.1", 1502)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    reading = await read_holding_register("127.0.0.1:1502", 42, 7)
    assert (reading.address, reading.value) == (42, 0x1234)
    assert writer.request == struct.pack(">HHHBBHH", 1, 0, 6, 7, 3, 42, 1)
    assert writer.closed


@pytest.mark.anyio
async def test_modbus_exception_is_not_a_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(struct.pack(">HHHB", 1, 0, 3, 1) + bytes([0x83, 2]))
    reader.feed_eof()
    writer = FakeWriter()

    async def connect(_host: str, _port: int):
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    with pytest.raises(ValueError, match="rejected"):
        await read_holding_register("127.0.0.1", 0)
    assert writer.closed


@pytest.mark.parametrize(
    "host", ["example.com", "8.8.8.8", "127.0.0.1/path", "user@127.0.0.1"]
)
def test_external_or_ambiguous_hosts_are_rejected(host: str) -> None:
    with pytest.raises(ValueError):
        _tcp_endpoint(host)


@pytest.mark.anyio
async def test_invalid_address_and_unit_never_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_connection(*_args):
        raise AssertionError("Must not connect")

    monkeypatch.setattr(asyncio, "open_connection", no_connection)
    with pytest.raises(ValueError, match="address"):
        await read_holding_register("127.0.0.1", 65536)
    with pytest.raises(ValueError, match="Unit"):
        await read_holding_register("127.0.0.1", 0, 0)


@pytest.mark.anyio
async def test_runtime_publishes_real_register_value_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = state.make_entry(
        DeviceConfig(
            id="modbus-test-register", host="127.0.0.1", register_address=42, unit_id=7
        )
    )
    state.registry.set(entry["config_id"], entry)
    calls: list[tuple[str, int, int]] = []

    async def successful_read(host: str, address: int, unit: int) -> HoldingRegister:
        calls.append((host, address, unit))
        return HoldingRegister(address, 1234)

    monkeypatch.setattr(state, "read_holding_register", successful_read)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    try:
        reading = await state.refresh_entry(entry)
        assert reading == {"connected": True, "holding_register_value": 1234}
        assert calls == [("127.0.0.1", 42, 7)]

        async def failed_read(_host: str, _address: int, _unit: int) -> HoldingRegister:
            raise TimeoutError

        monkeypatch.setattr(state, "read_holding_register", failed_read)
        failure = await state.refresh_entry(entry)
        assert failure == {"connected": False, "reason": "register_read_failed"}
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_unconfigured_runtime_has_no_demo_entity() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        entities = (await client.get("/entities")).json()["entities"]
        assert all(entity["id"] != "demo-device" for entity in entities)
        discovery = (await client.post("/discover", json={})).json()
        assert not discovery.get("devices")


def test_widget_is_bound_to_real_register_capability() -> None:
    root = Path(__file__).parents[1]
    package = json.loads(
        (root / "experiences/register/package.source.json").read_text()
    )
    widget = package["widgets"][0]
    assert widget["runtime"] == "declarative"
    assert widget["binding_slots"][0]["capability_requirements"] == [
        "holding_register_value"
    ]
    assert widget["binding_slots"][0]["binding_modes"] == ["read"]
    assert not any(
        action["type"].startswith("command")
        for action in widget["recipe"]["items"]
        if "action" in action
    )
