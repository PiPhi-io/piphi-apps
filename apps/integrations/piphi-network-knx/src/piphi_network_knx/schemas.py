from __future__ import annotations

import ipaddress
from enum import StrEnum

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TransportMode(StrEnum):
    AUTOMATIC = "automatic"
    TUNNELING_UDP = "tunneling_udp"
    TUNNELING_TCP = "tunneling_tcp"


class EntityType(StrEnum):
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    SWITCH = "switch"
    LIGHT = "light"


class DptType(StrEnum):
    SWITCH = "1.001"
    SCALING = "5.001"
    TEMPERATURE = "9.001"


_ENTITY_DPTS: dict[EntityType, set[DptType]] = {
    EntityType.BINARY_SENSOR: {DptType.SWITCH},
    EntityType.SENSOR: {DptType.SCALING, DptType.TEMPERATURE},
    EntityType.SWITCH: {DptType.SWITCH},
    EntityType.LIGHT: {DptType.SWITCH, DptType.SCALING},
}


class DatapointConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    entity_type: EntityType
    dpt: DptType
    state_address: str
    command_address: str | None = None
    writable: bool = False
    read_on_init: bool = True
    stale_after_seconds: int = Field(default=3600, ge=30, le=86400)

    @field_validator("state_address", "command_address")
    @classmethod
    def validate_group_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = value.split("/")
        if len(parts) != 3:
            raise ValueError("group address must use main/middle/sub format")
        try:
            main, middle, sub = (int(part) for part in parts)
        except ValueError as exc:
            raise ValueError("group address components must be integers") from exc
        if not (0 <= main <= 31 and 0 <= middle <= 7 and 0 <= sub <= 255):
            raise ValueError("group address is outside the KNX 3-level range")
        return f"{main}/{middle}/{sub}"

    @model_validator(mode="after")
    def validate_mapping(self) -> DatapointConfig:
        if self.dpt not in _ENTITY_DPTS[self.entity_type]:
            raise ValueError(f"DPT {self.dpt} is not supported for {self.entity_type}")
        if self.writable:
            if self.entity_type not in {EntityType.SWITCH, EntityType.LIGHT}:
                raise ValueError("only switch and light datapoints may be writable")
            if self.command_address is None:
                raise ValueError("writable datapoints require a command_address")
        elif self.command_address is not None:
            raise ValueError("command_address requires writable=true")
        return self


class DeviceConfig(RuntimeConfig):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    host: str
    port: int = Field(default=3671, ge=1, le=65535)
    alias: str | None = Field(default=None, max_length=120)
    transport: TransportMode = TransportMode.TUNNELING_UDP
    local_ip: str | None = None
    rate_limit: int = Field(default=10, ge=1, le=60)
    queue_size: int = Field(default=64, ge=1, le=512)
    connect_timeout_seconds: float = Field(default=10, ge=1, le=60)
    command_timeout_seconds: float = Field(default=5, ge=1, le=30)
    allow_writes: bool = False
    datapoints: list[DatapointConfig] = Field(default_factory=list, max_length=256)

    @field_validator("host", "local_ip")
    @classmethod
    def validate_ip_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(ipaddress.ip_address(value))
        except ValueError as exc:
            raise ValueError("must be an IPv4 or IPv6 address") from exc

    @model_validator(mode="after")
    def validate_datapoints(self) -> DeviceConfig:
        ids = [item.id for item in self.datapoints]
        if len(ids) != len(set(ids)):
            raise ValueError("datapoint ids must be unique")
        state_addresses = [item.state_address for item in self.datapoints]
        if len(state_addresses) != len(set(state_addresses)):
            raise ValueError("each state address may map to only one datapoint")
        if any(item.writable for item in self.datapoints) and not self.allow_writes:
            raise ValueError("allow_writes must be enabled for writable datapoints")
        return self
