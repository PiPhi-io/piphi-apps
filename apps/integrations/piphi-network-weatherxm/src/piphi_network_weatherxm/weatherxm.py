from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any

import httpx
from pydantic import SecretStr

from .settings import DEFAULT_WEATHERXM_BASE_URL

PLACEHOLDER_SECRETS = {"", "change-me", "your-api-token", "your-password", "your-email@example.com"}

WEATHER_CAPABILITIES: dict[str, tuple[str, str]] = {
    "temperature": ("temperature_c", "C"),
    "humidity": ("humidity_percent", "%"),
    "precipitation": ("precipitation_mm", "mm"),
    "wind_speed": ("wind_speed_ms", "m/s"),
    "wind_gust": ("wind_gust_ms", "m/s"),
    "wind_direction": ("wind_direction_deg", "deg"),
    "pressure": ("pressure_hpa", "hPa"),
    "uv_index": ("uv_index", "index"),
    "feels_like": ("feels_like_c", "C"),
    "precipitation_accumulated": ("precipitation_accumulated_mm", "mm"),
    "dew_point": ("dew_point_c", "C"),
    "solar_irradiance": ("solar_irradiance_w_m2", "W/m2"),
}


@dataclass(frozen=True)
class WeatherXMReading:
    metrics: dict[str, float | int | bool]
    units: dict[str, str]
    raw: dict[str, Any]
    latest_timestamp: str | None
    latency_ms: int
    device: dict[str, Any]
    observed_at: datetime


class WeatherXMError(RuntimeError):
    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class WeatherXMClient:
    def __init__(
        self,
        *,
        api_token: str | SecretStr | None = None,
        username: str | SecretStr | None = None,
        password: str | SecretStr | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_token = None if is_placeholder_secret(api_token) else secret_value(api_token)
        self.username = None if is_placeholder_secret(username) else secret_value(username)
        self.password = None if is_placeholder_secret(password) else secret_value(password)
        self.base_url = (base_url or DEFAULT_WEATHERXM_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._session = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._session.aclose()

    async def devices(self) -> list[dict[str, Any]]:
        payload = await self._get_json("/me/devices")
        return payload if isinstance(payload, list) else []

    async def device(self, station_id: str) -> dict[str, Any]:
        payload = await self._get_json(f"/me/devices/{station_id}")
        return payload if isinstance(payload, dict) else {"id": station_id}

    async def latest_reading(self, station_id: str) -> WeatherXMReading:
        started = perf_counter()
        device = await self.resolve_device(station_id)
        latency_ms = int((perf_counter() - started) * 1000)
        metrics, units, latest_timestamp = normalize_current_weather(device)
        observed_at = parse_source_timestamp(latest_timestamp)
        metrics["connected"] = True
        metrics["api_latency_ms"] = latency_ms
        units["connected"] = "bool"
        units["api_latency_ms"] = "ms"
        return WeatherXMReading(
            metrics=metrics,
            units=units,
            raw=device,
            latest_timestamp=latest_timestamp,
            latency_ms=latency_ms,
            device=device,
            observed_at=observed_at,
        )

    async def resolve_device(self, station_id: str | None = None) -> dict[str, Any]:
        if not station_id:
            raise ValueError("explicit WeatherXM station_id is required")
        return await self.device(station_id)

    async def _get_json(self, path: str) -> Any:
        try:
            response = await self._session.get(
                f"{self.base_url}{path}",
                headers=await self._headers(self._session),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            category = "auth" if status in {401, 403} else "quota" if status == 429 else "outage" if status >= 500 else "request"
            raise WeatherXMError(category) from None
        except (httpx.TimeoutException, httpx.NetworkError):
            raise WeatherXMError("outage") from None
        except (ValueError, TypeError):
            raise WeatherXMError("provider_contract") from None

    async def _headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        token = self.api_token or await self._login(client)
        return {
            "accept": "application/json",
            "authorization": f"Bearer {token}",
        }

    async def _login(self, client: httpx.AsyncClient) -> str:
        if not self.username or not self.password:
            raise ValueError("WeatherXM credentials require api_token or username/password")
        response = await client.post(
            f"{self.base_url}/auth/login",
            headers={"accept": "application/json"},
            json={"username": self.username, "password": self.password},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError("WeatherXM login response did not include a token")
        self.api_token = token
        return token


def normalize_current_weather(device: dict[str, Any]) -> tuple[dict[str, float | int | bool], dict[str, str], str | None]:
    metrics: dict[str, float | int | bool] = {}
    units: dict[str, str] = {}
    weather = device.get("current_weather")
    if not isinstance(weather, dict):
        return metrics, units, None

    for source_key, (capability_id, unit) in WEATHER_CAPABILITIES.items():
        value = weather.get(source_key)
        if is_number(value):
            metrics[capability_id] = value
            units[capability_id] = unit

    metrics_payload = device.get("metrics")
    if isinstance(metrics_payload, dict):
        qod_score = metrics_payload.get("qod_score")
        if is_number(qod_score):
            metrics["qod_score"] = qod_score
            units["qod_score"] = "score"

    timestamp = weather.get("timestamp")
    return metrics, units, timestamp if isinstance(timestamp, str) else None


def parse_source_timestamp(value: str | None, *, now: datetime | None = None) -> datetime:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        raise WeatherXMError("provider_contract") from None
    if parsed.tzinfo is None:
        raise WeatherXMError("provider_contract")
    parsed = parsed.astimezone(UTC)
    if parsed > (now or datetime.now(UTC)) + timedelta(minutes=5):
        raise WeatherXMError("provider_contract")
    return parsed


def device_display_name(device: dict[str, Any], fallback: str) -> str:
    for key in ("label", "name", "address"):
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def is_placeholder_secret(secret: str | SecretStr | None) -> bool:
    value = secret_value(secret)
    return value is None or value.strip().lower() in PLACEHOLDER_SECRETS


def secret_value(secret: str | SecretStr | None) -> str | None:
    return secret.get_secret_value() if isinstance(secret, SecretStr) else secret


def is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def has_credentials(config: Any) -> bool:
    if not is_placeholder_secret(getattr(config, "api_token", None)):
        return True
    return not (
        is_placeholder_secret(getattr(config, "username", None))
        or is_placeholder_secret(getattr(config, "password", None))
    )


def resolve_station_id(config: Any) -> str:
    return str(getattr(config, "station_id", "")).strip()
