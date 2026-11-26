from __future__ import annotations

import re

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    gateway_url: AnyHttpUrl = Field(description="PiPhi BLE gateway v1 base URL")
    gateway_token: SecretStr = Field(min_length=1, description="Gateway bearer token")
    bind_key: SecretStr | None = Field(
        default=None,
        description="Optional 16-byte BTHome bind key, accepted only as 32 hexadecimal characters",
    )
    device_handle: str = Field(description="Opaque ble_ handle issued by the PiPhi BLE gateway")
    alias: str | None = None
    poll_interval_seconds: int = Field(default=10, ge=2, le=300)
    stale_after_seconds: int = Field(default=180, ge=30, le=86400)

    @field_validator("gateway_url")
    @classmethod
    def require_tls(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https" and value.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("gateway_url must use HTTPS (HTTP is allowed only for loopback)")
        return value

    @field_validator("device_handle")
    @classmethod
    def reject_raw_address(cls, value: str) -> str:
        value = value.strip()
        if re.fullmatch(r"ble_[0-9a-f]{32}", value) is None:
            raise ValueError("device_handle must be an opaque gateway handle, not a MAC address")
        return value

    @field_validator("bind_key")
    @classmethod
    def validate_bind_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip().lower()
        if re.fullmatch(r"[0-9a-f]{32}", raw) is None:
            raise ValueError("bind_key must contain exactly 32 hexadecimal characters")
        return SecretStr(raw)
