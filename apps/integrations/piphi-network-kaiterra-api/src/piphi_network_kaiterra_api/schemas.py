from __future__ import annotations

import os
from uuid import UUID
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    alias: str | None = None
    api_key: SecretStr
    base_url: str | None = None
    device_udid: SecretStr
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)

    @field_validator("device_udid")
    @classmethod
    def validate_device_udid(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().strip()
        try:
            normalized = str(UUID(raw))
        except ValueError as exc:
            raise ValueError("device_udid must be a Kaiterra UUID") from exc
        return SecretStr(normalized)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("api_key is required")
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
