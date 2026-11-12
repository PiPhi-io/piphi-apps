from __future__ import annotations

import re

from pydantic import Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str = Field(description="BLE device address (Linux BlueZ MAC address)")
    alias: str | None = None
    poll_interval_seconds: int = Field(default=60, ge=30, le=3600)

    @field_validator("host")
    @classmethod
    def validate_address(cls, value: str) -> str:
        address = value.strip().upper()
        if re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address) is None:
            raise ValueError("host must be a BLE MAC address")
        return address
