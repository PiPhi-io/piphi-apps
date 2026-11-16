from __future__ import annotations

import os
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    station_id: str = Field(min_length=1)
    host: str | None = None
    alias: str | None = None
    api_token: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    base_url: str | None = None
    poll_interval_seconds: int = Field(default=300, ge=15)
    service_name: str | None = None

    @field_validator("station_id")
    @classmethod
    def validate_station_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("station_id is required")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None or value.rstrip("/") == "https://api.weatherxm.com/api/v1":
            return value
        parsed = urlparse(value)
        test_override = os.getenv("PIPHI_ALLOW_TEST_BASE_URL") == "1"
        if test_override and parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return value
        raise ValueError("base_url is fixed to the WeatherXM mobile-account API endpoint")
