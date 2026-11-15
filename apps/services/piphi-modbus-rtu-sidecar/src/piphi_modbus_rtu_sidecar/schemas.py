from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from piphi_runtime_kit_python import RuntimeConfig


class RegisterProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    unit_id: int = Field(ge=1, le=247)
    address: int = Field(ge=0, le=65535)
    area: Literal["coil", "discrete_input", "input_register", "holding_register"] = (
        "holding_register"
    )
    data_type: Literal[
        "bool",
        "uint16",
        "int16",
        "uint32",
        "int32",
        "uint64",
        "int64",
        "float32",
        "float64",
        "string",
    ] = "uint16"
    byte_order: Literal["ABCD", "BADC", "CDAB", "DCBA"] = "ABCD"
    string_length: int | None = Field(default=None, ge=1, le=250)
    string_encoding: Literal["ascii", "utf-8"] = "ascii"
    enum_values: dict[str, int] | None = Field(default=None, min_length=1, max_length=256)
    bit_mask: int | None = Field(default=None, ge=1)
    unit: str | None = Field(default=None, max_length=32)
    scale: float = Field(default=1.0, allow_inf_nan=False)
    offset: float = Field(default=0.0, allow_inf_nan=False)
    writable: bool = False
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)

    @property
    def width(self) -> int:
        if self.data_type == "string":
            return ((self.string_length or 0) + 1) // 2
        if self.data_type in {"uint64", "int64", "float64"}:
            return 4
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

    @model_validator(mode="after")
    def validate_type_options(self):
        if self.data_type == "string":
            if self.string_length is None:
                raise ValueError("string data_type requires string_length")
            if self.scale != 1 or self.offset != 0:
                raise ValueError("string data_type does not support scale or offset")
            if self.minimum is not None or self.maximum is not None:
                raise ValueError("string data_type does not support numeric bounds")
        elif self.string_length is not None:
            raise ValueError("string_length is only valid for string data_type")
        if self.enum_values is not None:
            if self.data_type not in {"uint16", "int16", "uint32", "int32", "uint64", "int64"}:
                raise ValueError("enum_values require an integer data_type")
            if self.scale != 1 or self.offset != 0:
                raise ValueError("enum_values do not support scale or offset")
            if len(self.enum_values.values()) != len(set(self.enum_values.values())):
                raise ValueError("enum_values must map to unique integers")
            bits = self.width * 16
            lower = -(1 << (bits - 1)) if self.data_type.startswith("int") else 0
            upper = (1 << (bits - 1)) - 1 if self.data_type.startswith("int") else (1 << bits) - 1
            if any(value < lower or value > upper for value in self.enum_values.values()):
                raise ValueError("enum value exceeds the data type range")
        if self.bit_mask is not None:
            if self.data_type not in {"uint16", "uint32", "uint64"}:
                raise ValueError("bit_mask requires an unsigned integer data_type")
            if self.bit_mask >= 1 << (self.width * 16):
                raise ValueError("bit_mask exceeds the data type width")
            if self.scale != 1 or self.offset != 0 or self.enum_values is not None:
                raise ValueError("bit_mask does not support transforms or enum_values")
            if self.writable:
                raise ValueError("bit_mask points are read-only")
        if self.writable and self.width > 123:
            raise ValueError("writable point exceeds FC16 quantity limit")
        return self


class DeviceConfig(RuntimeConfig):
    host: str = "modbus-rtu-sidecar"
    alias: str | None = None
    serial_port: str
    serial_mode: Literal["rtu", "ascii"] = "rtu"
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
