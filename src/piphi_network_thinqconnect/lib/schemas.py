from __future__ import annotations

from typing import Any

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ThinQDeviceConfig(RuntimeConfig):
    config_id: str | None = None
    device_id: str
    device_name: str | None = None
    device_type: str
    access_token: str = ""
    country_code: str
    client_id: str | None = None
    alias: str | None = None
    poll_interval_seconds: int | None = 60
    push_events_enabled: bool = False
    integration_id: str | None = None
    container_id: str | None = None
    simulation_mode: bool = False
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def require_live_credentials(self) -> ThinQDeviceConfig:
        if not self.simulation_mode and not self.access_token.strip():
            raise ValueError("access_token is required unless simulation_mode is enabled")
        return self


class ThinQDiscoveryRequest(BaseModel):
    access_token: str = ""
    country_code: str = "US"
    client_id: str | None = None
    simulation_mode: bool = False


class DeconfigureConfig(BaseModel):
    config: dict[str, Any]


class RuntimeConfigSnapshot(BaseModel):
    container_id: str
    integration_id: str | None = None
    driver_pid: int | None = None
    reason: str | None = None
    generation: int | None = None
    configs: list[ThinQDeviceConfig] = Field(default_factory=list)


class RuntimeConfigSyncResponse(BaseModel):
    status: str
    container_id: str
    reason: str | None = None
    generation: int | None = None
    applied: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    active_config_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CommandRequest(BaseModel):
    command: str
    entity_id: str | None = None
    device_id: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
