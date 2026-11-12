from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    site_id: int = Field(gt=0)
    api_key: SecretStr
    alias: str | None = "SolarEdge site"
    poll_interval_seconds: int = Field(default=900, ge=600, le=86400)
    summary_interval_seconds: int = Field(default=3600, ge=3600, le=86400)

    @field_validator("alias")
    @classmethod
    def normalize_alias(cls, value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    def secret_api_key(self) -> str:
        return self.api_key.get_secret_value()
