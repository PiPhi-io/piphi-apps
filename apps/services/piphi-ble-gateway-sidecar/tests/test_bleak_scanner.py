from __future__ import annotations

import sys
import types
import builtins
import asyncio

import pytest

from piphi_ble_gateway_sidecar.scanner import BleakCallbackScanner
from piphi_ble_gateway_sidecar.bluez import default_capability_adapter


@pytest.mark.anyio
async def test_bleak_winrt_style_path_uses_callback_without_dbus(monkeypatch) -> None:
    created = {}

    class FakeBleakScanner:
        def __init__(self, detection_callback, **kwargs):
            created["callback"] = detection_callback
            created["kwargs"] = kwargs

        async def start(self):
            created["started"] = True

        async def stop(self):
            created["stopped"] = True

    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakScanner=FakeBleakScanner))
    monkeypatch.setattr("piphi_ble_gateway_sidecar.scanner.platform.system", lambda: "Windows")
    real_import = builtins.__import__

    def no_linux_imports(name, *args, **kwargs):
        if name == "dbus" or name.startswith("dbus_fast"):
            raise AssertionError("Windows scanner path attempted to import a Linux D-Bus module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_linux_imports)
    scanner = BleakCallbackScanner()
    received = []
    async def receive(item):
        received.append(item)

    await scanner.start("active", receive)
    assert created["started"] is True
    assert created["kwargs"] == {"scanning_mode": "active"}
    assert scanner.backend == "bleak-winrt"
    device = types.SimpleNamespace(address="AA:BB:CC:DD:EE:FF", details={"address_type": "random"})
    data = types.SimpleNamespace(rssi=-61, tx_power=-10, connectable=True, service_uuids=["180f"], manufacturer_data={76: b"\x01"}, service_data={})
    created["callback"](device, data)
    await asyncio.sleep(0)
    assert len(received) == 1 and received[0].address_type == "random"
    await scanner.stop()
    assert created["stopped"] is True


def test_windows_default_capability_never_imports_dbus(monkeypatch) -> None:
    monkeypatch.setattr("piphi_ble_gateway_sidecar.bluez.platform.system", lambda: "Windows")
    real_import = builtins.__import__

    def no_linux_imports(name, *args, **kwargs):
        if name.startswith("dbus_fast"):
            raise AssertionError("Windows capability path attempted to import D-Bus")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_linux_imports)
    adapter = default_capability_adapter()
    assert adapter.__class__.__name__ == "NoopCapabilityAdapter"


@pytest.mark.anyio
async def test_partial_backend_start_failure_is_cleanly_retryable(monkeypatch) -> None:
    created = []

    class PartialScanner:
        def __init__(self, detection_callback, **kwargs):
            created.append(self)

        async def start(self):
            if len(created) == 1:
                raise RuntimeError("radio unavailable")

        async def stop(self):
            if len(created) == 1:
                raise AssertionError("watcher was never initialized")

    monkeypatch.setitem(sys.modules, "bleak", types.SimpleNamespace(BleakScanner=PartialScanner))
    scanner = BleakCallbackScanner()

    async def receive(_item):
        pass

    with pytest.raises(RuntimeError, match="radio unavailable"):
        await scanner.start("active", receive)
    await scanner.stop()
    await scanner.start("active", receive)
    await scanner.stop()
