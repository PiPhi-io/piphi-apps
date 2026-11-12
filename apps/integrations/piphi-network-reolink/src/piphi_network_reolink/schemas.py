from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, SecretStr, field_validator


class DeviceConfig(RuntimeConfig):
    host: str
    username: str
    password: SecretStr
    port: int | None = Field(default=None, ge=1, le=65535)
    use_https: bool | None = None
    alias: str | None = None
    poll_interval_seconds: int = Field(default=30, ge=10, le=3600)

    @field_validator("host", "username")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        return normalized
