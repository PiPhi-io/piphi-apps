from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface
from typing import Literal

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import Field, model_validator


class DeviceConfig(RuntimeConfig):
    host: IPv4Address
    port: int = Field(default=47808, ge=1, le=65535)
    device_instance: int = Field(ge=1, le=4194302)
    local_address: IPv4Interface
    local_device_instance: int = Field(default=4194000, ge=1, le=4194302)
    profile: Literal["kaiterra_sensedge_mini"] = "kaiterra_sensedge_mini"
    alias: str | None = None
    poll_interval_seconds: int = Field(default=60, ge=30, le=3600)

    @model_validator(mode="after")
    def validate_instances(self) -> "DeviceConfig":
        if self.local_device_instance == self.device_instance:
            raise ValueError("local_device_instance must differ from device_instance")
        if self.host not in self.local_address.network:
            raise ValueError("host must be on the same IPv4 subnet as local_address")
        return self

    @property
    def target_address(self) -> str:
        host = str(self.host)
        return host if self.port == 47808 else f"{host}:{self.port}"
