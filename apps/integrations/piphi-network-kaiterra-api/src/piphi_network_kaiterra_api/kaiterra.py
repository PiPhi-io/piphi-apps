from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from time import perf_counter
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.kaiterra.com/v1"
TEST_SENSEDGE_UDID = "00000000-0031-0101-0000-00007e57c0de"
TEST_LASER_EGG_UDID = "00000000-0001-0101-0000-00007e57c0de"
MAX_RETRY_AFTER_SECONDS = 3600.0
MAX_ATTEMPTS = 3

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
    # `pir` is deliberately excluded because it is occupancy-correlated.
    "atmospheric_pressure": ("pressure_pa", "Pa"),
    "light_clear": ("illuminance_lux", "lx"),
    "cct": ("color_temperature_k", "K"),
    "co": ("co_ppm", "ppm"),
    "no2": ("no2_ppb", "ppb"),
}


@dataclass(frozen=True, slots=True)
class KaiterraDeviceMetadata:
    name: str | None
    model: str | None
    firmware_version: str | None


@dataclass(frozen=True, slots=True)
class KaiterraReading:
    metrics: dict[str, float | int | bool]
    units: dict[str, str]
    latest_timestamp: str | None
    latency_ms: int
    observed_at: datetime
    rate_limit_remaining: int | None = None


class KaiterraError(RuntimeError):
    def __init__(self, category: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(category)
        self.category = category
        self.retry_after_seconds = retry_after_seconds


class KaiterraAuthError(KaiterraError):
    pass


class KaiterraRateLimitError(KaiterraError):
    pass


class KaiterraOutageError(KaiterraError):
    pass


class KaiterraContractError(KaiterraError):
    pass


class KaiterraSelectionError(KaiterraError):
    pass


class KaiterraClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[float], float] | None = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._api_key = api_key
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._sleep = sleep
        self._jitter = jitter or (lambda delay: random.uniform(0.0, min(delay * 0.1, 5.0)))
        self._max_attempts = max(1, int(max_attempts))
        self._owns_client = http_client is None
        self._session = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            headers={"accept": "application/json", "accept-encoding": "gzip"},
            transport=transport,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._session.aclose()

    async def device_metadata(self, device_udid: str) -> KaiterraDeviceMetadata:
        payload, _headers = await self._get_json(f"/devices/{device_udid}")
        return KaiterraDeviceMetadata(
            name=_optional_string(payload.get("name")),
            model=_optional_string(payload.get("model")),
            firmware_version=_optional_string(payload.get("firmware_version")),
        )

    async def latest_reading(self, device_udid: str) -> KaiterraReading:
        started = perf_counter()
        payload, headers = await self._get_json(f"/devices/{device_udid}/top")
        latency_ms = int((perf_counter() - started) * 1000)
        metrics, units, latest_timestamp = normalize_latest_reading(payload)
        if not metrics or latest_timestamp is None:
            raise KaiterraContractError("provider_contract")
        observed_at = parse_source_timestamp(latest_timestamp)
        metrics["connected"] = True
        metrics["api_latency_ms"] = latency_ms
        units["api_latency_ms"] = "ms"
        remaining = _rate_limit_remaining(headers)
        if remaining is not None:
            metrics["api_rate_limit_remaining"] = remaining
            units["api_rate_limit_remaining"] = "requests"
        return KaiterraReading(
            metrics=metrics,
            units=units,
            latest_timestamp=latest_timestamp,
            latency_ms=latency_ms,
            observed_at=observed_at,
            rate_limit_remaining=remaining,
        )

    async def _get_json(self, path: str) -> tuple[dict[str, Any], httpx.Headers]:
        last_network_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._session.get(
                    f"{self.base_url}{path}",
                    params={"key": self._api_key},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_network_error = exc
                if attempt == self._max_attempts:
                    raise KaiterraOutageError("transient_outage") from None
                await self._sleep(self._retry_delay(attempt, None))
                continue

            retry_after = _retry_after_seconds(response.headers)
            if response.status_code == 429:
                if attempt == self._max_attempts:
                    raise KaiterraRateLimitError(
                        "rate_limit", retry_after_seconds=retry_after
                    )
                await self._sleep(self._retry_delay(attempt, retry_after))
                continue
            if response.status_code >= 500:
                if attempt == self._max_attempts:
                    raise KaiterraOutageError(
                        "transient_outage", retry_after_seconds=retry_after
                    )
                await self._sleep(self._retry_delay(attempt, retry_after))
                continue
            if response.status_code == 401:
                raise KaiterraAuthError("authentication")
            if response.status_code == 403:
                raise KaiterraAuthError("authorization")
            if response.status_code == 404:
                raise KaiterraSelectionError("device_not_found")
            if response.status_code >= 400:
                raise KaiterraSelectionError("request_rejected")
            try:
                payload = response.json()
            except (ValueError, TypeError):
                raise KaiterraContractError("provider_contract") from None
            if not isinstance(payload, dict):
                raise KaiterraContractError("provider_contract")
            return payload, response.headers

        raise KaiterraOutageError("transient_outage") from last_network_error

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        base = retry_after if retry_after is not None else min(float(2 ** (attempt - 1)), 30.0)
        return min(MAX_RETRY_AFTER_SECONDS, max(base, 0.0) + max(self._jitter(base), 0.0))


def normalize_latest_reading(payload: dict[str, Any]) -> tuple[dict[str, float | int], dict[str, str], str | None]:
    metrics: dict[str, float | int] = {}
    units: dict[str, str] = {}
    latest_timestamp: str | None = None
    latest_observed_at: datetime | None = None
    series_items = payload.get("data")
    if not isinstance(series_items, list):
        raise KaiterraContractError("provider_contract")
    for series in series_items:
        if not isinstance(series, dict):
            continue
        capability = PARAMETER_CAPABILITIES.get(str(series.get("param") or ""))
        if capability is None:
            continue
        points = series.get("points")
        if not isinstance(points, list) or not points:
            continue
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for point in points:
            if not isinstance(point, dict) or not isinstance(point.get("ts"), str):
                continue
            try:
                candidates.append((parse_source_timestamp(point["ts"]), point))
            except KaiterraError:
                continue
        if not candidates:
            continue
        observed_at, point = max(candidates, key=lambda item: item[0])
        value = point.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        capability_id, default_unit = capability
        metrics[capability_id] = value
        units[capability_id] = default_unit
        if latest_observed_at is None or observed_at > latest_observed_at:
            latest_timestamp = str(point["ts"])
            latest_observed_at = observed_at
    return metrics, units, latest_timestamp


def parse_source_timestamp(value: str | None, *, now: datetime | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        raise KaiterraContractError("provider_contract") from None
    if parsed.tzinfo is None:
        raise KaiterraContractError("provider_contract")
    parsed = parsed.astimezone(UTC)
    if parsed > (now or datetime.now(UTC)) + timedelta(minutes=5):
        raise KaiterraContractError("provider_contract")
    return parsed


def _retry_after_seconds(headers: httpx.Headers, *, now: datetime | None = None) -> float | None:
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(float(value), 0.0))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value).astimezone(UTC)
        except (TypeError, ValueError, OverflowError):
            return None
        return min(MAX_RETRY_AFTER_SECONDS, max((retry_at - (now or datetime.now(UTC))).total_seconds(), 0.0))


def _rate_limit_remaining(headers: httpx.Headers) -> int | None:
    for name in ("RateLimit-Remaining", "X-RateLimit-Remaining"):
        value = headers.get(name)
        if value is None:
            continue
        try:
            return max(int(value), 0)
        except ValueError:
            continue
    return None


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
