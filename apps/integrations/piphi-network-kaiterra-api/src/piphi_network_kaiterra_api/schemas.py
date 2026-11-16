from __future__ import annotations

import os
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str | None = None
    alias: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    device_udid: str = Field(min_length=1)
    poll_interval_seconds: int = Field(default=300, ge=15)

    @field_validator("device_udid")
    @classmethod
    def validate_device_udid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("device_udid is required")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None or value.rstrip("/") == "https://api.kaiterra.com/v1":
            return value
        parsed = urlparse(value)
        test_override = os.getenv("PIPHI_ALLOW_TEST_BASE_URL") == "1"
        if test_override and parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return value
        raise ValueError("base_url is fixed to the official Kaiterra API endpoint")
