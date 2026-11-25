from __future__ import annotations

from enum import StrEnum

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, field_validator


def normalize_host(value: str) -> str:
    host = value.strip()
    if not host or any(character.isspace() for character in host):
        raise ValueError("host must not be empty or contain whitespace")
    if "://" in host or "/" in host or "\\" in host:
        raise ValueError("host must be a hostname or IP address without a URL scheme")
    return host


class TransportType(StrEnum):
    REMOTE_V2 = "remote_v2"
    ADB = "adb"


class DeviceConfig(RuntimeConfig):
    host: str = Field(min_length=1, max_length=253)
    alias: str | None = Field(default=None, max_length=128)
    transport: TransportType = TransportType.REMOTE_V2
    enable_controls: bool = Field(default=False, strict=True)
    adb_port: int = Field(default=5555, strict=True, ge=1, le=65535)
    adb_queue_capacity: int = Field(default=16, strict=True, ge=1, le=100)
    adb_connect_timeout_ms: int = Field(default=5_000, strict=True, ge=500, le=30_000)
    adb_operation_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=30_000)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return normalize_host(value)
