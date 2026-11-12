from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class TPLinkDeviceConfig(RuntimeConfig):
    config_id: str | None = None
    host: str
    alias: str | None = None
    integration_id: str | None = None
    username: str | None = None
    password: str | None = None
    container_id: str | None = None
    model_config = ConfigDict(extra="allow")

    @field_validator("username", "password", mode="before")
    @classmethod
    def _ignore_masked_secret_placeholder(cls, value: Any) -> str | None:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, dict) and value.get("__piphi_secret__"):
            return None
        return str(value)


class DeconfigureConfig(BaseModel):
    config: dict[str, Any]


class RuntimeConfigSnapshot(BaseModel):
    container_id: str
    integration_id: str | None = None
    driver_pid: int | None = None
    reason: str | None = None
    generation: int | None = None
    configs: list[TPLinkDeviceConfig] = Field(default_factory=list)


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
    target: dict[str, Any] = Field(default_factory=dict)


class EventRequest(BaseModel):
    event_type: str
    source: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
