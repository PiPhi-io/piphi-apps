from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, field_validator


def normalize_host(value: str) -> str:
    host = value.strip()
    if not host or any(character.isspace() for character in host):
        raise ValueError("host must not be empty or contain whitespace")
    if "://" in host or "/" in host or "\\" in host:
        raise ValueError("host must be a hostname or IP address without a URL scheme")
    return host


class DeviceConfig(RuntimeConfig):
    host: str = Field(min_length=1, max_length=253)
    alias: str | None = Field(default=None, max_length=128)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return normalize_host(value)
