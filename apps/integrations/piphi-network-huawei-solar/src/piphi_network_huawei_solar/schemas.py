from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, field_validator

from .sun2000 import local_endpoint


class DeviceConfig(RuntimeConfig):
    host: str
    alias: str | None = None
    poll_interval_seconds: int = Field(default=300, ge=60, le=3600)
    unit_id: int = Field(default=1, ge=0, le=247)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        name, port = local_endpoint(value)
        return f"[{name}]:{port}" if ":" in name else f"{name}:{port}"
