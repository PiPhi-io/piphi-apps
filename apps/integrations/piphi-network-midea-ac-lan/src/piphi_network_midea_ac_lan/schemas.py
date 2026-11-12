from __future__ import annotations

from pydantic import Field, model_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str = Field(min_length=1)
    alias: str | None = None
    port: int = Field(default=6444, ge=1, le=65535)
    midea_device_id: int | None = Field(default=None, ge=1)
    token: str | None = None
    key: str | None = None
    poll_interval_seconds: int = Field(default=30, ge=5, le=3600)
    controls_enabled: bool = False

    @model_validator(mode="after")
    def require_complete_local_credentials(self) -> "DeviceConfig":
        if bool(self.token) != bool(self.key):
            raise ValueError("token and key must be configured together")
        return self
