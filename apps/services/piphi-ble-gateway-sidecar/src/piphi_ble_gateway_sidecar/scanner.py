from __future__ import annotations

from collections.abc import Awaitable, Callable
import asyncio
import platform
from typing import Protocol

from .ble_models import Advertisement, ScanMode

DetectionCallback = Callable[[Advertisement], Awaitable[None]]


class Scanner(Protocol):
    backend: str
    adapter: str
    receiver_kind: str

    async def start(self, mode: ScanMode, callback: DetectionCallback) -> None: ...
    async def stop(self) -> None: ...


class BleakCallbackScanner:
    """Continuous Bleak callback scanner (BlueZ on Linux, WinRT on Windows)."""

    def __init__(self, adapter: str | None = None) -> None:
        self.adapter = adapter or "default"
        system = platform.system().lower()
        self.backend = "bleak-winrt" if system == "windows" else "bleak-bluez" if system == "linux" else "bleak"
        self.receiver_kind = "local"
        self._scanner = None
        self._callback: DetectionCallback | None = None
        self._tasks: set[asyncio.Task] = set()

    async def start(self, mode: ScanMode, callback: DetectionCallback) -> None:
        from bleak import BleakScanner

        self._callback = callback

        def detected(device, advertisement_data) -> None:
            details = getattr(device, "details", None)
            address_type = "unknown"
            if isinstance(details, dict):
                address_type = str(details.get("AddressType") or details.get("address_type") or "unknown")
            advert = Advertisement(
                address=str(device.address),
                observed_monotonic_ms=__import__("time").monotonic_ns() // 1_000_000,
                rssi=int(getattr(advertisement_data, "rssi", -127)),
                tx_power=getattr(advertisement_data, "tx_power", None),
                connectable=bool(getattr(advertisement_data, "connectable", False)),
                address_type=address_type,
                service_uuids=tuple(str(item).lower() for item in (advertisement_data.service_uuids or ())),
                manufacturer_data=dict(advertisement_data.manufacturer_data or {}),
                service_data=dict(advertisement_data.service_data or {}),
            )
            task = asyncio.create_task(callback(advert))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        kwargs = {"scanning_mode": "passive" if mode == "passive" else "active"}
        if self.adapter != "default":
            kwargs["adapter"] = self.adapter
        self._scanner = BleakScanner(detection_callback=detected, **kwargs)
        await self._scanner.start()

    async def stop(self) -> None:
        scanner, self._scanner = self._scanner, None
        if scanner is not None:
            await scanner.stop()
        tasks, self._tasks = self._tasks, set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class CapabilityAdapter(Protocol):
    async def diagnostics(self) -> dict: ...
    async def recover(self) -> bool: ...


class NoopCapabilityAdapter:
    async def diagnostics(self) -> dict:
        return {"available": False}

    async def recover(self) -> bool:
        return False
