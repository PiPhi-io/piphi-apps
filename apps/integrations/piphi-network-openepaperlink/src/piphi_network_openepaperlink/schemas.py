from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import ConfigDict, field_validator

from .ap import local_endpoint


class DeviceConfig(RuntimeConfig):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    host: str
    alias: str | None = None
    poll_interval_seconds: int = 300

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        local_endpoint(value)
        return value.lower()

    @field_validator("poll_interval_seconds")
    @classmethod
    def validate_interval(cls, value: int) -> int:
        if not 60 <= value <= 3600:
            raise ValueError("poll_interval_seconds must be between 60 and 3600")
        return value
