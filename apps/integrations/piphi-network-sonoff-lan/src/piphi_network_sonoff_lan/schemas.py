from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, field_validator

from .diy import local_endpoint


class DeviceConfig(RuntimeConfig):
    host: str
    diy_device_id: str
    alias: str | None = None
    poll_interval_seconds: int = Field(default=300, ge=60, le=3600)

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        host, port = local_endpoint(value)
        return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
