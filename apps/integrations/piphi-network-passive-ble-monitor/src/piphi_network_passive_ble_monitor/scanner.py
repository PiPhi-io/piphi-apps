"""The BlueZ/Bleak transport boundary; tests replace this function."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .bthome import UnsupportedAdvertisement, decode_service_data


@dataclass(frozen=True)
class SensorAdvertisement:
    address: str
    metrics: dict[str, Any]
    rssi: int | None


async def scan_bthome(*, timeout: float = 5.0) -> list[SensorAdvertisement]:
    from bleak import BleakScanner

    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    result: list[SensorAdvertisement] = []
    for device, advertisement in discovered.values():
        try:
            metrics = decode_service_data(advertisement.service_data)
        except UnsupportedAdvertisement:
            continue
        if metrics is None:
            continue
        result.append(
            SensorAdvertisement(
                address=device.address.upper(),
                metrics=metrics,
                rssi=getattr(advertisement, "rssi", None),
            )
        )
    return result
