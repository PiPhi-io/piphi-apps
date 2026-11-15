from __future__ import annotations

import json
from pathlib import Path
from time import monotonic_ns

import pytest

from piphi_ble_gateway_sidecar.ble_models import Advertisement, Matcher
from piphi_ble_gateway_sidecar.gateway import Gateway
from piphi_ble_gateway_sidecar.scanner import NoopCapabilityAdapter


class FakeScanner:
    backend = "fake-winrt"
    adapter = "radio-0"
    receiver_kind = "local"

    def __init__(self) -> None:
        self.starts: list[str] = []
        self.stops = 0
        self.callback = None

    async def start(self, mode, callback) -> None:
        self.starts.append(mode)
        self.callback = callback

    async def stop(self) -> None:
        self.stops += 1

    async def emit(self, advert: Advertisement) -> None:
        assert self.callback
        await self.callback(advert)


class LinuxCapabilities:
    async def diagnostics(self) -> dict:
        return {"available": True, "bluez": {"powered": True}}

    async def recover(self) -> bool:
        return True


def make_gateway(tmp_path: Path, scanner=None, capabilities=None) -> Gateway:
    return Gateway(
        scanner or FakeScanner(), capabilities,
        secret_path=tmp_path / "key", checkpoint_path=tmp_path / "checkpoint.json"
    )


def advert(timestamp: int, address: str = "AA:BB:CC:DD:EE:FF", rssi: int = -55) -> Advertisement:
    return Advertisement(address, timestamp, rssi, service_uuids=("180f",), manufacturer_data={76: b"\x01\x02"})


@pytest.mark.anyio
async def test_fake_scanner_lifecycle_and_mode_arbitration(tmp_path: Path) -> None:
    scanner = FakeScanner()
    gateway = make_gateway(tmp_path, scanner)
    await gateway.start()
    assert scanner.starts == []
    await gateway.register("passive", "p" * 16, Matcher(service_uuids=frozenset({"180f"})), "passive", 4)
    await gateway.register("auto", "a" * 16, Matcher(manufacturer_ids=frozenset({76})), "auto", 4)
    await gateway.register("active", "x" * 16, Matcher(device_handles=frozenset({"ble_known"})), "active", 4)
    assert scanner.starts == ["passive", "auto", "active"]
    assert gateway.plan() == "active"
    await gateway.unregister("active", "x" * 16)
    assert gateway.plan() == "auto"
    await gateway.stop()
    assert scanner.stops == 4


@pytest.mark.anyio
async def test_flood_is_bounded_and_slow_consumers_are_isolated(tmp_path: Path) -> None:
    gateway = make_gateway(tmp_path)
    await gateway.start()
    slow = await gateway.register("slow", "s" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 3)
    fast = await gateway.register("fast", "f" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 10)
    observed_monotonic_ms = monotonic_ns() // 1_000_000
    for index in range(20):
        await gateway.ingest(advert(observed_monotonic_ms, address=f"AA:BB:CC:00:00:{index:02X}"))
    assert len(slow.queue) == 3 and slow.dropped == 17
    assert len(fast.queue) == 10 and fast.dropped == 10
    assert slow.high_water == 3 and fast.high_water == 10


@pytest.mark.anyio
async def test_dedup_out_of_order_and_changed_rssi(tmp_path: Path) -> None:
    gateway = make_gateway(tmp_path)
    await gateway.start()
    consumer = await gateway.register("one", "o" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 10)
    await gateway.ingest(advert(10_000))
    await gateway.ingest(advert(10_500))
    await gateway.ingest(advert(9_999, rssi=-40))
    await gateway.ingest(advert(10_600, rssi=-40))
    assert len(consumer.queue) == 2
    assert gateway.observations_deduplicated == 2
    assert consumer.queue[-1]["rssi"] == -40


@pytest.mark.anyio
async def test_checkpoint_replay_is_marked_bounded_and_redacted(tmp_path: Path) -> None:
    first = make_gateway(tmp_path)
    await first.start()
    await first.register("one", "o" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 10)
    await first.ingest(advert(10_000))
    handle = next(iter(first.consumers["one"].latest))
    await first.stop()
    persisted = (tmp_path / "checkpoint.json").read_text()
    assert "AA:BB" not in persisted and "key" not in persisted

    second = make_gateway(tmp_path)
    await second.start()
    consumer = await second.register("two", "t" * 16, Matcher(device_handles=frozenset({handle})), "auto", 10)
    assert len(consumer.queue) == 1
    assert consumer.queue[0]["replayed"] is True
    assert consumer.queue[0]["device_handle"] == handle


@pytest.mark.anyio
async def test_stale_checkpoint_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "key").write_bytes(b"k" * 32)
    (tmp_path / "checkpoint.json").write_text(json.dumps({"saved_at_ms": 1, "observations": [{"sequence": 99}]}))
    gateway = make_gateway(tmp_path)
    await gateway.start()
    assert gateway.sequence == 0
    assert gateway._checkpoint == []


@pytest.mark.anyio
async def test_restart_is_clean_and_linux_capabilities_are_optional(tmp_path: Path) -> None:
    scanner = FakeScanner()
    gateway = make_gateway(tmp_path, scanner, LinuxCapabilities())
    await gateway.start()
    await gateway.register("one", "o" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 4)
    await gateway.restart()
    diagnostics = await gateway.diagnostics()
    assert scanner.starts == ["auto", "auto"]
    assert diagnostics["reconnects"] == 1
    assert diagnostics["platform_capabilities"]["bluez"]["powered"] is True


@pytest.mark.anyio
async def test_windows_like_backend_has_no_dbus_requirement(tmp_path: Path) -> None:
    gateway = make_gateway(tmp_path, FakeScanner(), NoopCapabilityAdapter())
    await gateway.start()
    await gateway.register("win", "w" * 16, Matcher(manufacturer_ids=frozenset({76})), "active", 4)
    diagnostics = await gateway.diagnostics()
    assert diagnostics["backend"] == "fake-winrt"
    assert diagnostics["platform_capabilities"] == {"supported": False, "available": False}
