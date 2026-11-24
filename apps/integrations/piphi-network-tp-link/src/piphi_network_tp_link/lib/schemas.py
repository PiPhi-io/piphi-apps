from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from piphi_runtime_kit_python import RuntimeConfig


class TPLinkDeviceConfig(RuntimeConfig):
    config_id: str | None = None
    host: str = Field(min_length=1, max_length=255)
    alias: str | None = None
    integration_id: str | None = None
    username: SecretStr | None = Field(default=None, repr=False)
    password: SecretStr | None = Field(default=None, repr=False)
    controls_enabled: bool = False
    certified_profile: str | None = Field(default=None, max_length=128)
    allowed_commands: list[str] = Field(default_factory=list, max_length=8)
    poll_interval_seconds: int = Field(default=30, ge=10, le=3600)
    container_id: str | None = None
    model_config = ConfigDict(extra="allow")

    @field_validator("username", "password", mode="before")
    @classmethod
    def _ignore_masked_secret_placeholder(cls, value: Any) -> Any:
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, dict) and value.get("__piphi_secret__"):
            return None
        return str(value)

    @field_validator("host")
    @classmethod
    def _normalize_host(cls, value: str) -> str:
        normalized = value.strip().rstrip(".")
        if not normalized:
            raise ValueError("host must not be empty")
        return normalized

    @model_validator(mode="after")
    def _validate_credentials_and_controls(self) -> "TPLinkDeviceConfig":
        if bool(self.username) != bool(self.password):
            raise ValueError("username and password must be configured together")
        if self.controls_enabled and not self.certified_profile:
            raise ValueError("controls_enabled requires a certified_profile")
        if not self.controls_enabled and self.allowed_commands:
            raise ValueError("allowed_commands requires controls_enabled")
        return self

    def secret(self, name: str) -> str | None:
        value = getattr(self, name)
        return value.get_secret_value() if value is not None else None


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
