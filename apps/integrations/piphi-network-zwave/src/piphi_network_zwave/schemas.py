from __future__ import annotations

from pydantic import Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    network_id: str = "primary"
    alias: str | None = None
    event_poll_interval_seconds: float = Field(default=1.0, ge=0.25, le=30.0)

    @field_validator("alias")
    @classmethod
    def normalize_alias(cls, value: str | None) -> str | None:
        token = str(value or "").strip()
        return token or None

    @field_validator("network_id")
    @classmethod
    def validate_network_id(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if token != "primary":
            raise ValueError("only the primary managed Z-Wave network is supported")
        return token
