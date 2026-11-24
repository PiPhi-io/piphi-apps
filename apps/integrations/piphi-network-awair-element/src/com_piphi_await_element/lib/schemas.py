from typing import Any

from piphi_runtime_kit_python import RuntimeConfig
from piphi_runtime_kit_python import RuntimeConfigSnapshot as KitRuntimeConfigSnapshot
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AwairElement(RuntimeConfig):
    config_id: str | None = None
    device_ip: str = Field(min_length=1, max_length=255)
    device_identity: str = Field(min_length=3, max_length=128)
    container_id: str | None = None
    integration_id: str | None = None
    device_mac: str | None = None
    poll_interval_seconds: int = Field(default=30, ge=10, le=3600)
    model_config = ConfigDict(extra="forbid")

    @field_validator("device_ip", "device_identity")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("device_identity")
    @classmethod
    def validate_awair_identity(cls, value: str) -> str:
        normalized = value.upper()
        prefix = "AWAIR-ELEM-"
        suffix = normalized.removeprefix(prefix)
        if not normalized.startswith(prefix) or not suffix or not all(
            character.isalnum() or character in "-_" for character in suffix
        ):
            raise ValueError("device_identity must be a discovered AWAIR-ELEM-* identity")
        return normalized


class DeconfigureConfig(BaseModel):
    config: dict


class RuntimeConfigSnapshot(KitRuntimeConfigSnapshot):
    configs: list[RuntimeConfig] = Field(default_factory=list)


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
    contract_version: str | None = None
    entity_id: str | None = None
    device_id: str | None = None
    config_id: str | None = None
    capability: str | None = None
    capability_requirements: list[str] = Field(default_factory=list)
    args: dict = Field(default_factory=dict)
    params: dict = Field(default_factory=dict)
    target: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)


class EventRequest(BaseModel):
    event_type: str
    source: str | None = None
    payload: dict = Field(default_factory=dict)
