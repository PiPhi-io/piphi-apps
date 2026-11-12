from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    friendly_name: str
    ieee_address: str | None = None
    alias: str | None = None
    model_id: str | None = None
    vendor: str | None = None
    description: str | None = None
    device_type: str | None = None
    mqtt_server: str | None = None
    mqtt_topic: str | None = None
    mqtt_base_topic: str = "zigbee2mqtt"
    sidecar_base_url: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    capability_metadata: dict[str, Any] = Field(default_factory=dict)
    exposes: list[dict[str, Any]] = Field(default_factory=list)
    definition: dict[str, Any] = Field(default_factory=dict)

    @field_validator("friendly_name", "mqtt_base_topic")
    @classmethod
    def validate_required_token(cls, value: str) -> str:
        token = str(value or "").strip().strip("/")
        if not token:
            raise ValueError("value is required")
        return token

    @field_validator("sidecar_base_url")
    @classmethod
    def normalize_sidecar_base_url(cls, value: str | None) -> str | None:
        token = str(value or "").strip().rstrip("/")
        return token or None

    @field_validator("mqtt_server")
    @classmethod
    def normalize_mqtt_server(cls, value: str | None) -> str | None:
        token = str(value or "").strip()
        return token or None

    @field_validator("mqtt_topic")
    @classmethod
    def normalize_mqtt_topic(cls, value: str | None) -> str | None:
        token = str(value or "").strip().strip("/")
        return token or None
