from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, SecretStr, field_validator, model_validator


class DeviceConfig(RuntimeConfig):
    host: str = Field(min_length=1, max_length=255)
    alias: str | None = None
    port: int = Field(default=6444, ge=1, le=65535)
    midea_device_id: int | None = Field(default=None, ge=1)
    token: SecretStr | None = Field(default=None, repr=False)
    key: SecretStr | None = Field(default=None, repr=False)
    poll_interval_seconds: int = Field(default=30, ge=5, le=3600)
    controls_enabled: bool = False

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("host must not be empty")
        return normalized

    @model_validator(mode="after")
    def require_complete_local_credentials(self) -> DeviceConfig:
        token = self.token.get_secret_value() if self.token is not None else ""
        key = self.key.get_secret_value() if self.key is not None else ""
        if bool(token) != bool(key):
            raise ValueError("token and key must be configured together")
        return self
