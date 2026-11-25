from __future__ import annotations

from pathlib import Path

import pytest

from piphi_ble_gateway_sidecar.ble_models import Matcher
from piphi_ble_gateway_sidecar.bluez import BlueZCapabilityAdapter
from piphi_ble_gateway_sidecar.gateway import Gateway


class FakeBlueZTransport:
    def __init__(self) -> None:
        self.available = True
        self.powered = False
        self.discovering = False
        self.recoveries = 0

    async def diagnostics(self, adapter: str) -> dict:
        assert adapter == "hci-test"
        return {
            "available": self.available,
            "adapter_count": 1 if self.available else 0,
            "adapter_powered": self.powered,
            "adapter_discovering": self.discovering,
        }

    async def recover(self, adapter: str) -> bool:
        assert adapter == "hci-test"
        self.recoveries += 1
        if not self.available:
            return False
        self.powered = True
        self.discovering = True
        return True


class FakeScanner:
    backend = "fake-bluez"
    adapter = "hci-test"
    receiver_kind = "local"

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    async def start(self, mode, callback) -> None:
        self.starts += 1

    async def stop(self) -> None:
        self.stops += 1


@pytest.mark.anyio
async def test_bluez_adapter_reports_bounded_health_and_narrow_recovery() -> None:
    transport = FakeBlueZTransport()
    adapter = BlueZCapabilityAdapter("hci-test", transport)
    diagnostics = await adapter.diagnostics()
    assert diagnostics["supported"] is True
    assert diagnostics["available"] is True
    assert diagnostics["adapter_powered"] is False
    assert "rfkill_soft_blocked" in diagnostics
    assert await adapter.recover() is True
    assert transport.recoveries == 1
    assert (await adapter.diagnostics())["adapter_powered"] is True


@pytest.mark.anyio
async def test_supervisor_recovers_power_loss_and_adapter_reappearance(tmp_path: Path) -> None:
    transport = FakeBlueZTransport()
    scanner = FakeScanner()
    gateway = Gateway(
        scanner,
        BlueZCapabilityAdapter("hci-test", transport),
        secret_path=tmp_path / "key",
        checkpoint_path=tmp_path / "checkpoint",
    )
    await gateway.start()
    await gateway.register("consumer", "c" * 16, Matcher(service_uuids=frozenset({"180f"})), "auto", 4)
    assert scanner.starts == 1

    transport.available = False
    gateway.scanner_state = "failed"
    assert await gateway.supervise_once() is False
    assert transport.recoveries == 1

    transport.available = True
    gateway._next_reconnect_at = 0
    assert await gateway.supervise_once() is True
    assert transport.recoveries == 2
    assert scanner.starts == 2
    assert gateway.reconnects == 1
    await gateway.stop()
