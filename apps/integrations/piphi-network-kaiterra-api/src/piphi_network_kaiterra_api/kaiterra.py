from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    # Motion is intentionally not published: it is occupancy-correlated data.
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
    observed_at: datetime


class KaiterraError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class KaiterraClient:
    def __init__(self, *, api_key: str, base_url: str | None = None, timeout: float = 10.0) -> None:
        self._api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._session = httpx.AsyncClient(timeout=timeout, headers={"accept": "application/json"})

    async def close(self) -> None:
        await self._session.aclose()

    async def device_metadata(self, device_udid: str) -> dict[str, Any]:
        return await self._get_json(f"/devices/{device_udid}")

    async def latest_reading(self, device_udid: str) -> KaiterraReading:
        started = perf_counter()
        payload = await self._get_json(f"/devices/{device_udid}/top")
        latency_ms = int((perf_counter() - started) * 1000)
        metrics, units, latest_timestamp = normalize_latest_reading(payload)
        observed_at = parse_source_timestamp(latest_timestamp)
        metrics["connected"] = True
        metrics["api_latency_ms"] = latency_ms
        units["api_latency_ms"] = "ms"
        return KaiterraReading(
            metrics=metrics,
            units=units,
            raw=payload,
            latest_timestamp=latest_timestamp,
            latency_ms=latency_ms,
            observed_at=observed_at,
        )

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            response = await self._session.get(
                f"{self.base_url}{path}",
                params={"key": self._api_key},
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            category = "auth" if status in {401, 403} else "quota" if status == 429 else "outage" if status >= 500 else "request"
            raise KaiterraError(category) from None
        except (httpx.TimeoutException, httpx.NetworkError):
            raise KaiterraError("outage") from None
        except (ValueError, TypeError):
            raise KaiterraError("provider_contract") from None


def normalize_latest_reading(payload: dict[str, Any]) -> tuple[dict[str, float | int], dict[str, str], str | None]:
    metrics: dict[str, float | int] = {}
    units: dict[str, str] = {}
    latest_timestamp: str | None = None
    latest_observed_at: datetime | None = None

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
        valid_points = [
            point for point in points
            if isinstance(point, dict) and isinstance(point.get("ts"), str)
        ]
        if not valid_points:
            continue
        try:
            point = max(valid_points, key=lambda candidate: parse_source_timestamp(candidate["ts"]))
        except KaiterraError:
            continue
        value = point.get("value")
        if not isinstance(value, int | float):
            continue
        capability_id, default_unit = capability
        metrics[capability_id] = value
        units[capability_id] = default_unit
        ts = point.get("ts")
        if isinstance(ts, str):
            observed_at = parse_source_timestamp(ts)
            if latest_observed_at is None or observed_at > latest_observed_at:
                latest_timestamp = ts
                latest_observed_at = observed_at

    return metrics, units, latest_timestamp


def is_placeholder_api_key(api_key: str | None) -> bool:
    return not api_key or api_key.strip() in {"", "change-me", "your-api-key"}


def parse_source_timestamp(value: str | None, *, now: datetime | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        raise KaiterraError("provider_contract") from None
    if parsed.tzinfo is None:
        raise KaiterraError("provider_contract")
    parsed = parsed.astimezone(UTC)
    if parsed > (now or datetime.now(UTC)) + timedelta(minutes=5):
        raise KaiterraError("provider_contract")
    return parsed


def resolve_device_udid(config: Any) -> str:
    return str(getattr(config, "device_udid", "")).strip()
