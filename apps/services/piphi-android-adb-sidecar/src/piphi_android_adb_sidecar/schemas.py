from __future__ import annotations

import ipaddress
import re

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, field_validator


class DeviceConfig(RuntimeConfig):
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5555, strict=True, ge=1, le=65535)
    alias: str | None = Field(default=None, max_length=128)
    service_name: str | None = Field(default=None, max_length=128)
    queue_capacity: int = Field(default=16, strict=True, ge=1, le=100)
    connect_timeout_ms: int = Field(default=5_000, strict=True, ge=500, le=30_000)
    operation_timeout_ms: int = Field(default=5_000, strict=True, ge=100, le=30_000)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        host = value.strip()
        if not host or any(character.isspace() for character in host):
            raise ValueError("host must not be empty or contain whitespace")
        if "://" in host or "/" in host or "\\" in host:
            raise ValueError("host must be a hostname or IP address without a URL scheme")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.rstrip(".").split(".")
            if not all(
                label
                and len(label) <= 63
                and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("host must be a valid IPv4 address or DNS hostname") from None
        else:
            if address.version != 4:
                raise ValueError("IPv6 ADB endpoints are not supported in this release")
        return host
