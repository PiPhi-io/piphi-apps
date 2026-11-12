from __future__ import annotations

from typing import Any

import httpx
import pytest

from piphi_network_weatherxm import weatherxm
from piphi_network_weatherxm.schemas import DeviceConfig
from piphi_network_weatherxm.weatherxm import (
    WeatherXMClient,
    device_display_name,
    has_credentials,
    is_placeholder_secret,
    normalize_current_weather,
    resolve_station_id,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def response(payload: Any, *, status_code: int = 200, url: str = "https://api.weatherxm.test") -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))


class FakeAsyncClient:
    get_responses: list[httpx.Response] = []
    post_responses: list[httpx.Response] = []
    calls: list[dict[str, Any]] = []

    def __init__(self, *, timeout: float = 10.0) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        self.calls.append({"method": "GET", "url": url, "headers": headers})
        return self.get_responses.pop(0)

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, str]) -> httpx.Response:
        self.calls.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return self.post_responses.pop(0)


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> type[FakeAsyncClient]:
    FakeAsyncClient.get_responses = []
    FakeAsyncClient.post_responses = []
    FakeAsyncClient.calls = []
    monkeypatch.setattr(weatherxm.httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


def weather_payload(**overrides: Any) -> dict[str, Any]:
    current_weather = {
        "timestamp": "2026-05-11T10:00:00Z",
        "temperature": 21.5,
        "humidity": 48,
        "precipitation": 0.2,
        "wind_speed": 3.4,
        "wind_gust": 5.6,
        "wind_direction": 270,
        "pressure": 1015.2,
        "uv_index": 4,
        "feels_like": 20.8,
        "precipitation_accumulated": 1.2,
        "dew_point": 9.1,
        "solar_irradiance": 385.0,
    }
    current_weather.update(overrides)
    return {"id": "station-1", "current_weather": current_weather, "metrics": {"qod_score": 0.97}}


def test_normalize_current_weather_maps_full_weatherxm_payload() -> None:
    metrics, units, timestamp = normalize_current_weather(weather_payload())

    assert timestamp == "2026-05-11T10:00:00Z"
    assert metrics["temperature_c"] == 21.5
    assert metrics["humidity_percent"] == 48
    assert metrics["wind_direction_deg"] == 270
    assert metrics["qod_score"] == 0.97
    assert units["pressure_hpa"] == "hPa"
    assert units["solar_irradiance_w_m2"] == "W/m2"


@pytest.mark.parametrize(
    ("weather_key", "capability_id", "unit", "value"),
    [
        ("temperature", "temperature_c", "C", 19.4),
        ("humidity", "humidity_percent", "%", 61),
        ("precipitation", "precipitation_mm", "mm", 0.4),
        ("wind_speed", "wind_speed_ms", "m/s", 2.8),
        ("wind_gust", "wind_gust_ms", "m/s", 7.1),
        ("wind_direction", "wind_direction_deg", "deg", 315),
        ("pressure", "pressure_hpa", "hPa", 1009.8),
        ("uv_index", "uv_index", "index", 6),
        ("feels_like", "feels_like_c", "C", 18.2),
        ("precipitation_accumulated", "precipitation_accumulated_mm", "mm", 3.5),
        ("dew_point", "dew_point_c", "C", 7.6),
        ("solar_irradiance", "solar_irradiance_w_m2", "W/m2", 512.3),
    ],
)
def test_normalize_current_weather_maps_each_supported_weather_field(
    weather_key: str,
    capability_id: str,
    unit: str,
    value: float | int,
) -> None:
    metrics, units, _timestamp = normalize_current_weather({"current_weather": {weather_key: value}})

    assert metrics == {capability_id: value}
    assert units == {capability_id: unit}


def test_normalize_current_weather_accepts_integer_zero_values() -> None:
    metrics, units, _timestamp = normalize_current_weather({"current_weather": {"precipitation": 0}})

    assert metrics == {"precipitation_mm": 0}
    assert units == {"precipitation_mm": "mm"}


@pytest.mark.parametrize("timestamp", ["2026-05-11T10:00:00Z", "", "local-time"])
def test_normalize_current_weather_returns_string_timestamps(timestamp: str) -> None:
    _metrics, _units, result = normalize_current_weather({"current_weather": {"timestamp": timestamp}})

    assert result == timestamp


@pytest.mark.parametrize("timestamp", [None, 1715421600, {"at": "now"}])
def test_normalize_current_weather_ignores_non_string_timestamps(timestamp: object) -> None:
    _metrics, _units, result = normalize_current_weather({"current_weather": {"timestamp": timestamp}})

    assert result is None


@pytest.mark.parametrize("payload", [{}, {"current_weather": None}, {"current_weather": []}])
def test_normalize_current_weather_handles_missing_or_invalid_weather_blocks(payload: dict[str, Any]) -> None:
    metrics, units, timestamp = normalize_current_weather(payload)

    assert metrics == {}
    assert units == {}
    assert timestamp is None


@pytest.mark.parametrize("value", [True, False, "23.1", None, {"value": 23.1}])
def test_normalize_current_weather_ignores_non_numeric_weather_values(value: object) -> None:
    metrics, units, _timestamp = normalize_current_weather({"current_weather": {"temperature": value}})

    assert metrics == {}
    assert units == {}


@pytest.mark.parametrize("qod_score", [0, 0.72, 1])
def test_normalize_current_weather_maps_numeric_qod_scores(qod_score: float | int) -> None:
    metrics, units, _timestamp = normalize_current_weather({"current_weather": {}, "metrics": {"qod_score": qod_score}})

    assert metrics == {"qod_score": qod_score}
    assert units == {"qod_score": "score"}


@pytest.mark.parametrize("qod_score", [True, "0.72", None, []])
def test_normalize_current_weather_ignores_non_numeric_qod_scores(qod_score: object) -> None:
    metrics, units, _timestamp = normalize_current_weather({"current_weather": {}, "metrics": {"qod_score": qod_score}})

    assert "qod_score" not in metrics
    assert "qod_score" not in units


@pytest.mark.parametrize("secret", [None, "", "change-me", "CHANGE-ME", " your-api-token ", "your-password"])
def test_is_placeholder_secret_recognizes_empty_and_scaffold_values(secret: str | None) -> None:
    assert is_placeholder_secret(secret)


@pytest.mark.parametrize("secret", ["token", "real-password", "weatherxm@example.com"])
def test_is_placeholder_secret_allows_real_values(secret: str) -> None:
    assert not is_placeholder_secret(secret)


def test_has_credentials_accepts_bearer_token() -> None:
    assert has_credentials(DeviceConfig(id="wxm", station_id="123", api_token="token"))


def test_has_credentials_accepts_username_password_pair() -> None:
    assert has_credentials(DeviceConfig(id="wxm", station_id="123", username="user@example.com", password="secret"))


@pytest.mark.parametrize(
    "config",
    [
        DeviceConfig(id="wxm", station_id="123", api_token="change-me"),
        DeviceConfig(id="wxm", station_id="123", username="user@example.com"),
        DeviceConfig(id="wxm", station_id="123", password="secret"),
        DeviceConfig(id="wxm", station_id="123", username="your-email@example.com", password="secret"),
    ],
)
def test_has_credentials_rejects_incomplete_or_placeholder_credentials(config: DeviceConfig) -> None:
    assert not has_credentials(config)


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        (DeviceConfig(id="wxm", station_id="station-1", host="host-1"), "station-1"),
        (DeviceConfig(id="wxm", host="host-1"), "host-1"),
        (DeviceConfig(id="wxm", device_id="runtime-device"), "runtime-device"),
        (DeviceConfig(id="wxm"), "wxm"),
        (DeviceConfig(id="wxm", station_id="  station-2  "), "station-2"),
    ],
)
def test_resolve_station_id_uses_stable_identity_priority(config: DeviceConfig, expected: str) -> None:
    assert resolve_station_id(config) == expected


@pytest.mark.parametrize(
    ("device", "expected"),
    [
        ({"label": "Backyard", "name": "wxm-123", "address": "Athens"}, "Backyard"),
        ({"label": " ", "name": "wxm-123", "address": "Athens"}, "wxm-123"),
        ({"label": "", "name": "", "address": "Athens"}, "Athens"),
        ({}, "fallback"),
    ],
)
def test_device_display_name_prefers_human_fields(device: dict[str, Any], expected: str) -> None:
    assert device_display_name(device, "fallback") == expected


def test_client_strips_base_url_trailing_slashes() -> None:
    client = WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test/api/v1/")

    assert client.base_url == "https://api.weatherxm.test/api/v1"


def test_client_treats_placeholder_credentials_as_missing() -> None:
    client = WeatherXMClient(api_token="change-me", username="your-email@example.com", password="your-password")

    assert client.api_token is None
    assert client.username is None
    assert client.password is None


@pytest.mark.anyio
async def test_client_devices_returns_list_payload(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response([{"id": "station-1"}])]

    assert await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").devices() == [
        {"id": "station-1"}
    ]


@pytest.mark.anyio
async def test_client_devices_returns_empty_list_for_unexpected_payload(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response({"id": "station-1"})]

    assert await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").devices() == []


@pytest.mark.anyio
async def test_client_device_returns_device_payload(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response({"id": "station-1", "label": "Backyard"})]

    result = await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").device("station-1")

    assert result == {"id": "station-1", "label": "Backyard"}


@pytest.mark.anyio
async def test_client_device_falls_back_to_requested_station_id_for_unexpected_payload(
    fake_httpx: type[FakeAsyncClient],
) -> None:
    fake_httpx.get_responses = [response([{"id": "wrong-shape"}])]

    result = await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").device("station-1")

    assert result == {"id": "station-1"}


@pytest.mark.anyio
async def test_client_resolve_device_uses_explicit_station_id(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response({"id": "station-2"})]

    result = await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").resolve_device("station-2")

    assert result["id"] == "station-2"
    assert fake_httpx.calls[0]["url"] == "https://api.weatherxm.test/me/devices/station-2"


@pytest.mark.anyio
async def test_client_resolve_device_uses_first_account_device(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response([{"id": "station-1"}, {"id": "station-2"}])]

    result = await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").resolve_device()

    assert result == {"id": "station-1"}


@pytest.mark.anyio
async def test_client_resolve_device_raises_when_account_has_no_devices(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response([])]

    with pytest.raises(httpx.HTTPStatusError, match="no devices"):
        await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").resolve_device()


@pytest.mark.anyio
async def test_client_latest_reading_adds_connectivity_and_latency_metrics(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.get_responses = [response(weather_payload(temperature=22.2))]

    reading = await WeatherXMClient(api_token="token", base_url="https://api.weatherxm.test").latest_reading("station-1")

    assert reading.metrics["connected"] is True
    assert reading.metrics["temperature_c"] == 22.2
    assert isinstance(reading.metrics["api_latency_ms"], int)
    assert reading.units["connected"] == "bool"
    assert reading.latest_timestamp == "2026-05-11T10:00:00Z"


@pytest.mark.anyio
async def test_client_headers_use_existing_bearer_token() -> None:
    headers = await WeatherXMClient(api_token="token")._headers(FakeAsyncClient())

    assert headers == {"accept": "application/json", "authorization": "Bearer token"}


@pytest.mark.anyio
async def test_client_headers_login_with_username_password_and_cache_token(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.post_responses = [response({"token": "jwt-token"}, url="https://api.weatherxm.test/auth/login")]
    client = WeatherXMClient(username="user@example.com", password="secret", base_url="https://api.weatherxm.test")

    headers = await client._headers(FakeAsyncClient())

    assert headers["authorization"] == "Bearer jwt-token"
    assert client.api_token == "jwt-token"
    assert fake_httpx.calls[0]["method"] == "POST"
    assert fake_httpx.calls[0]["url"] == "https://api.weatherxm.test/auth/login"
    assert fake_httpx.calls[0]["json"] == {"username": "user@example.com", "password": "secret"}


@pytest.mark.anyio
async def test_client_login_rejects_response_without_token(fake_httpx: type[FakeAsyncClient]) -> None:
    fake_httpx.post_responses = [response({"refreshToken": "refresh"})]
    client = WeatherXMClient(username="user@example.com", password="secret", base_url="https://api.weatherxm.test")

    with pytest.raises(ValueError, match="did not include a token"):
        await client._headers(FakeAsyncClient())


@pytest.mark.anyio
async def test_client_login_requires_token_or_username_password() -> None:
    client = WeatherXMClient(base_url="https://api.weatherxm.test")

    with pytest.raises(ValueError, match="require api_token"):
        await client._headers(FakeAsyncClient())
