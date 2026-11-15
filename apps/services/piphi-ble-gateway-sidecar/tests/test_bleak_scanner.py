from __future__ import annotations

import sys
import types
import builtins
import asyncio

import pytest

from piphi_ble_gateway_sidecar.scanner import BleakCallbackScanner


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
