from __future__ import annotations

import re

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

_VERSION_RE = re.compile(r"^\d+(?:\.\d+)?$")


class TuyaDeviceConfig(RuntimeConfig):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    host: str
    tuya_device_id: str = Field(
        validation_alias=AliasChoices(
            "tuya_device_id",
            "tuyaDeviceId",
            "vendor_device_id",
            "vendorDeviceId",
            "dev_id",
            "devId",
        )
    )
    local_key: str = Field(validation_alias=AliasChoices("local_key", "localKey"))
    alias: str | None = None
    device_type: str = "plug"
    version: str = "3.3"
    switch: int = Field(default=1, ge=1)
    fan_speed_dp: int = Field(default=3, ge=1)
    fan_speed_max: int = Field(default=3, ge=1)
    fan_oscillate_dp: int | None = Field(default=None, ge=1)
    fan_mode_dp: int | None = Field(default=None, ge=1)
    cover_control_dp: int = Field(default=1, ge=1)
    cover_position_dp: int | None = Field(default=None, ge=1)
    climate_target_temp_dp: int = Field(default=16, ge=1)
    climate_current_temp_dp: int | None = Field(default=None, ge=1)
    climate_mode_dp: int | None = Field(default=None, ge=1)
    climate_temp_scale: float = Field(default=1.0, gt=0)
    humidifier_target_humidity_dp: int = Field(default=103, ge=1)
    humidifier_current_humidity_dp: int | None = Field(default=None, ge=1)
    humidifier_mode_dp: int | None = Field(default=None, ge=1)
    humidifier_humidity_scale: float = Field(default=1.0, gt=0)
    purifier_speed_dp: int = Field(default=4, ge=1)
    purifier_speed_max: int = Field(default=3, ge=1)
    purifier_mode_dp: int | None = Field(default=None, ge=1)
    purifier_aqi_dp: int | None = Field(default=None, ge=1)
    purifier_aqi_scale: float = Field(default=1.0, gt=0)
    poll_interval_seconds: int = Field(default=60, ge=10)
    api_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_region", "apiRegion"),
    )
    api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_key", "apiKey"),
    )
    api_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_secret", "apiSecret"),
    )
    api_device_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("api_device_id", "apiDeviceId"),
    )

    @field_validator(
        "host",
        "tuya_device_id",
        "local_key",
        "alias",
        "device_type",
        "version",
        "api_region",
        "api_key",
        "api_secret",
        "api_device_id",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value):
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        if not value or any(character.isspace() for character in value):
            raise ValueError("host must be a non-empty hostname or IP address")
        return value

    @field_validator("tuya_device_id", "local_key")
    @classmethod
    def _validate_required_strings(cls, value: str) -> str:
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        if not value or not _VERSION_RE.match(value):
            raise ValueError("version must look like 3.3, 3.4, or 3.5")
        return value

    @model_validator(mode="after")
    def _validate_cloud_fields(self):
        cloud_values = [self.api_region, self.api_key, self.api_secret]
        if any(cloud_values) and not all(cloud_values):
            raise ValueError(
                "api_region, api_key, and api_secret must all be provided together for cloud discovery"
            )
        return self
