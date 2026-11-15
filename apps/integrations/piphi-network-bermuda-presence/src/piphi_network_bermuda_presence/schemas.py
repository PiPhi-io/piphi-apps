from __future__ import annotations

import re

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class ReceiverConfig(BaseModel):
    receiver_id: str = Field(min_length=1, max_length=256)
    area_id: str = Field(min_length=1, max_length=128)
    area_name: str = Field(min_length=1, max_length=128)
    kind: str = Field(default="unknown", max_length=64)
    rssi_offset_db: float = Field(default=0, ge=-30, le=30)
    radius_m: float = Field(default=20, gt=0, le=100)


class DeviceConfig(RuntimeConfig):
    gateway_url: str
    api_token: SecretStr
    consumer_id: str = Field(min_length=1, max_length=128)
    selected_device_handles: list[str] = Field(min_length=1, max_length=128)
    receivers: list[ReceiverConfig] = Field(default_factory=list, max_length=256)
    topology_revision: int = Field(default=0, ge=0)
    consider_home_seconds: int = Field(default=180, ge=30, le=3600)
    stale_seconds: int = Field(default=30, ge=5, le=300)
    reference_power_dbm: int = Field(default=-59, ge=-100, le=-20)
    attenuation_factor: float = Field(default=2.0, ge=1.0, le=5.0)
    smoothing_samples: int = Field(default=5, ge=1, le=20)
    area_switch_margin_m: float = Field(default=1.0, ge=0.1, le=20)
    area_switch_samples: int = Field(default=3, ge=1, le=20)
    max_velocity_m_s: float = Field(default=12.0, ge=0.5, le=100)
    alias: str | None = None
    poll_interval_seconds: int = Field(default=2, ge=1, le=30)

    @field_validator("gateway_url")
    @classmethod
    def valid_gateway_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("gateway_url must use HTTPS (HTTP is allowed only for loopback)")
        return value.rstrip("/")

    @field_validator("selected_device_handles")
    @classmethod
    def unique_handles(cls, value: list[str]) -> list[str]:
        if any(re.fullmatch(r"ble_[0-9a-f]{32}", handle) is None for handle in value) or len(value) != len(set(value)):
            raise ValueError("selected_device_handles must be unique opaque ble_ handles")
        return value

    @model_validator(mode="after")
    def required_gateway_settings(self) -> DeviceConfig:
        if self.stale_seconds >= self.consider_home_seconds:
            raise ValueError("stale_seconds must be less than consider_home_seconds")
        receiver_ids = [item.receiver_id for item in self.receivers]
        if len(receiver_ids) != len(set(receiver_ids)):
            raise ValueError("receiver_id values must be unique")
        return self
