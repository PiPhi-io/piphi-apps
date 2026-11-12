from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.kaiterra.com/v1"
TEST_SENSEDGE_UDID = "00000000-0031-0101-0000-00007e57c0de"
TEST_LASER_EGG_UDID = "00000000-0001-0101-0000-00007e57c0de"

PARAMETER_CAPABILITIES: dict[str, tuple[str, str]] = {
    "rco2": ("co2_ppm", "ppm"),
    "ro3": ("ozone_ppb", "ppb"),
    "rpm1c": ("pm1_ug_m3", "ug/m3"),
    "rpm25c": ("pm25_ug_m3", "ug/m3"),
    "rpm10c": ("pm10_ug_m3", "ug/m3"),
    "rhumid": ("humidity_percent", "%"),
    "rtemp": ("temperature_c", "C"),
    "tvoc": ("tvoc_ppb", "ppb"),
    "rtvoc": ("tvoc_ppb", "ppb"),
    "pir": ("motion_detected", "x"),
    "atmospheric_pressure": ("pressure_pa", "Pa"),
    "light_clear": ("illuminance_lux", "lx"),
    "cct": ("color_temperature_k", "K"),
    "co": ("co_ppm", "ppm"),
    "no2": ("no2_ppb", "ppb"),
}


@dataclass(frozen=True)
class KaiterraReading:
    metrics: dict[str, float | int]
    units: dict[str, str]
    raw: dict[str, Any]
    latest_timestamp: str | None
    latency_ms: int


class KaiterraClient:
    def __init__(self, *, api_key: str, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    async def device_metadata(self, device_udid: str) -> dict[str, Any]:
        return await self._get_json(f"/devices/{device_udid}")

    async def latest_reading(self, device_udid: str) -> KaiterraReading:
        started = perf_counter()
        payload = await self._get_json(f"/devices/{device_udid}/top")
        latency_ms = int((perf_counter() - started) * 1000)
        metrics, units, latest_timestamp = normalize_latest_reading(payload)
        metrics["connected"] = True
        metrics["api_latency_ms"] = latency_ms
        units["api_latency_ms"] = "ms"
        return KaiterraReading(
            metrics=metrics,
            units=units,
            raw=payload,
            latest_timestamp=latest_timestamp,
            latency_ms=latency_ms,
        )

    async def _get_json(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}{path}",
                params={"key": self.api_key},
                headers={"accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}


def normalize_latest_reading(payload: dict[str, Any]) -> tuple[dict[str, float | int], dict[str, str], str | None]:
    metrics: dict[str, float | int] = {}
    units: dict[str, str] = {}
    latest_timestamp: str | None = None

    for series in payload.get("data", []):
        if not isinstance(series, dict):
            continue
        param = str(series.get("param") or "")
        capability = PARAMETER_CAPABILITIES.get(param)
        if capability is None:
            continue
        points = series.get("points")
        if not isinstance(points, list) or not points:
            continue
        point = points[-1]
        if not isinstance(point, dict):
            continue
        value = point.get("value")
        if not isinstance(value, int | float):
            continue
        capability_id, default_unit = capability
        metrics[capability_id] = value
        units[capability_id] = str(series.get("units") or default_unit)
        ts = point.get("ts")
        if isinstance(ts, str):
            latest_timestamp = max(latest_timestamp, ts) if latest_timestamp else ts

    return metrics, units, latest_timestamp


def is_placeholder_api_key(api_key: str | None) -> bool:
    return not api_key or api_key.strip() in {"", "change-me", "your-api-key"}


def resolve_device_udid(config: Any) -> str:
    return str(
        getattr(config, "device_udid", None)
        or getattr(config, "host", None)
        or getattr(config, "id", "")
    )
