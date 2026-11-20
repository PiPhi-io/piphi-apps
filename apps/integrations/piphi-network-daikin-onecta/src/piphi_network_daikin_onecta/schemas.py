from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import ConfigDict, Field, SecretStr, field_validator


class DeviceConfig(RuntimeConfig):
    """Core-authored OAuth account configuration delivered to the runtime."""

    model_config = ConfigDict(extra="forbid")

    oauth_subject: str
    access_token: SecretStr
    alias: str | None = None
    poll_interval_seconds: int = Field(default=900, ge=300, le=3600)
    enable_climate_control: bool = False

    @field_validator("oauth_subject")
    @classmethod
    def non_empty_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("access_token")
    @classmethod
    def non_empty_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value
