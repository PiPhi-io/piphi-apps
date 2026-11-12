from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path

import httpx
import pytest

from piphi_network_huawei_solar import state
from piphi_network_huawei_solar.main import app
from piphi_network_huawei_solar.schemas import DeviceConfig
from piphi_network_huawei_solar.sun2000 import (
    InverterReading,
    local_endpoint,
    read_sun2000,
)


class FakeWriter:
    def __init__(self) -> None:
        self.requests = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.requests += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.anyio
async def test_reads_documented_registers_and_scales_energy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(
        struct.pack(">HHHB", 1, 0, 7, 1)
        + bytes([3, 4])
        + struct.pack(">i", -1200)
        + struct.pack(">HHHB", 2, 0, 7, 1)
        + bytes([3, 4])
        + struct.pack(">I", 1456)
    )
    reader.feed_eof()
    writer = FakeWriter()

    async def connect(host: str, port: int):
        assert (host, port) == ("127.0.0.1", 1502)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", connect)
    reading = await read_sun2000("127.0.0.1:1502")
    assert reading == InverterReading(active_power_w=-1200, daily_yield_kwh=14.56)
    assert writer.requests == (
        struct.pack(">HHHBBHH", 1, 0, 6, 1, 3, 32080, 2)
        + struct.pack(">HHHBBHH", 2, 0, 6, 1, 3, 32114, 2)
    )
    assert writer.closed


@pytest.mark.anyio
async def test_exception_response_is_not_a_reading(
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
        await read_sun2000("127.0.0.1")
    assert writer.closed


@pytest.mark.parametrize(
    "host", ["example.com", "8.8.8.8", "127.0.0.1/path", "user@127.0.0.1"]
)
def test_nonlocal_or_ambiguous_hosts_rejected(host: str) -> None:
    with pytest.raises(ValueError):
        local_endpoint(host)


@pytest.mark.anyio
async def test_out_of_range_unit_never_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_connect(*_args):
        raise AssertionError("must not connect")

    monkeypatch.setattr(asyncio, "open_connection", no_connect)
    with pytest.raises(ValueError, match="unit ID"):
        await read_sun2000("127.0.0.1", 248)


@pytest.mark.anyio
async def test_runtime_publishes_actual_reading_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = state.make_entry(
        DeviceConfig(id="huawei-test", host="127.0.0.1", unit_id=0)
    )
    state.registry.set(entry["config_id"], entry)
    calls: list[tuple[str, int]] = []

    async def successful_read(host: str, unit_id: int) -> InverterReading:
        calls.append((host, unit_id))
        return InverterReading(active_power_w=2040, daily_yield_kwh=8.5)

    monkeypatch.setattr(state, "read_sun2000", successful_read)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    try:
        metrics = await state.refresh_entry(entry)
        assert metrics == {
            "connected": True,
            "active_power_w": 2040,
            "daily_yield_kwh": 8.5,
        }
        assert calls == [("127.0.0.1", 0)]

        async def failed_read(_host: str, _unit_id: int) -> InverterReading:
            raise TimeoutError

        monkeypatch.setattr(state, "read_sun2000", failed_read)
        assert await state.refresh_entry(entry) == {
            "connected": False,
            "reason": "inverter_read_failed",
        }
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


def test_widget_consumes_only_read_only_metrics() -> None:
    root = Path(__file__).parents[1]
    package = json.loads(
        (root / "experiences/production/package.source.json").read_text()
    )
    widget = package["widgets"][0]
    assert widget["runtime"] == "declarative"
    assert {slot["capability_requirements"][0] for slot in widget["binding_slots"]} == {
        "active_power_w",
        "daily_yield_kwh",
    }
    assert all(slot["binding_modes"] == ["read"] for slot in widget["binding_slots"])
