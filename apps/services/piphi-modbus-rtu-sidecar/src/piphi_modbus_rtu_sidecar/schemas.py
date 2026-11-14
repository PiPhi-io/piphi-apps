from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from piphi_runtime_kit_python import RuntimeConfig


class RegisterProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    unit_id: int = Field(ge=1, le=247)
    address: int = Field(ge=0, le=65535)
    area: Literal["coil", "discrete_input", "input_register", "holding_register"] = (
        "holding_register"
    )
    data_type: Literal["bool", "uint16", "int16", "uint32", "int32", "float32"] = (
        "uint16"
    )
    byte_order: Literal["ABCD", "BADC", "CDAB", "DCBA"] = "ABCD"
    unit: str | None = Field(default=None, max_length=32)
    scale: float = Field(default=1.0, allow_inf_nan=False)
    offset: float = Field(default=0.0, allow_inf_nan=False)
    writable: bool = False
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @property
    def width(self) -> int:
        return 2 if self.data_type in {"uint32", "int32", "float32"} else 1

    @field_validator("scale")
    @classmethod
    def nonzero_scale(cls, value: float) -> float:
        if value == 0:
            raise ValueError("scale must not be zero")
        return value

    @field_validator("data_type")
    @classmethod
    def area_matches_type(cls, value: str, info):
        area = info.data.get("area", "holding_register")
        if area in {"coil", "discrete_input"} and value != "bool":
            raise ValueError("bit areas require bool data_type")
        if area in {"input_register", "holding_register"} and value == "bool":
            raise ValueError("register areas require a numeric data_type")
        return value


class DeviceConfig(RuntimeConfig):
    host: str = "modbus-rtu-sidecar"
    alias: str | None = None
    serial_port: str
    baud_rate: int = Field(default=9600, ge=1200, le=921600)
    parity: Literal["N", "E", "O"] = "N"
    stop_bits: Literal[1, 2] = 1
    data_bits: Literal[7, 8] = 8
    response_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    queue_capacity: int = Field(default=100, ge=1, le=1000)
    event_capacity: int = Field(default=1000, ge=10, le=10000)
    profile_id: str = Field(default="inline-profile", pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    profile_version: str = Field(default="1.0.0", min_length=1, max_length=64)
    profile_provenance: str = Field(default="user-reviewed", min_length=1, max_length=200)
    registers: list[RegisterProfile] = Field(min_length=1, max_length=256)

    @field_validator("registers")
    @classmethod
    def unique_registers(cls, value: list[RegisterProfile]) -> list[RegisterProfile]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("point ids must be unique")
        occupied: set[tuple[int, str, int]] = set()
        for item in value:
            if item.address + item.width - 1 > 65535:
                raise ValueError("point width exceeds address space")
            for address in range(item.address, item.address + item.width):
                target = (item.unit_id, item.area, address)
                if target in occupied:
                    raise ValueError("point address ranges must not overlap")
                occupied.add(target)
            if item.writable and item.area in {"discrete_input", "input_register"}:
                raise ValueError("read-only Modbus areas cannot be writable")
            if item.minimum is not None and item.maximum is not None and item.minimum > item.maximum:
                raise ValueError("minimum must not exceed maximum")
        return value
