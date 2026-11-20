from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import ConfigDict, Field, SecretStr, field_validator


class DeviceConfig(RuntimeConfig):
    model_config = ConfigDict(extra="forbid")

    host: str
    username: str
    password: SecretStr
    alias: str | None = None
    poll_interval_seconds: int = Field(default=60, ge=60, le=3600)

    @field_validator("host", "username")
    @classmethod
    def non_empty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("password")
    @classmethod
    def non_empty_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value
