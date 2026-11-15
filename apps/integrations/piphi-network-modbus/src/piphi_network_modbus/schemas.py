from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from piphi_runtime_kit_python import RuntimeConfig


class PointProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    unit_id: int = Field(ge=1, le=247)
    address: int = Field(ge=0, le=65535)
    area: Literal["coil", "discrete_input", "input_register", "holding_register"] = "holding_register"
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


CompositeEntityType = Literal["light", "fan", "cover", "climate"]
CompositeArgument = Literal[
    "brightness",
    "color_temp",
    "mode",
    "speed",
    "oscillating",
    "position",
    "temperature_c",
]

STATE_ROLES: dict[str, set[str]] = {
    "light": {"power", "brightness_percent", "color_temp_percent", "mode"},
    "fan": {"power", "fan_speed_percent", "oscillating", "mode"},
    "cover": {"position_percent", "movement_state"},
    "climate": {
        "power",
        "temperature_c",
        "target_temperature_c",
        "mode",
        "fan_speed_percent",
    },
}
COMMAND_ARGUMENTS: dict[str, dict[str, str | None]] = {
    "light": {
        "turn_on": None,
        "turn_off": None,
        "set_brightness": "brightness",
        "set_color_temp": "color_temp",
        "set_mode": "mode",
    },
    "fan": {
        "turn_on": None,
        "turn_off": None,
        "set_fan_speed": "speed",
        "set_oscillate": "oscillating",
        "set_mode": "mode",
    },
    "cover": {
        "open_cover": None,
        "close_cover": None,
        "stop_cover": None,
        "set_cover_position": "position",
    },
    "climate": {
        "turn_on": None,
        "turn_off": None,
        "set_temperature": "temperature_c",
        "set_mode": "mode",
        "set_fan_speed": "speed",
    },
}

BOOLEAN_ROLES = {"power", "oscillating"}
TEXT_ROLES = {"mode", "movement_state"}
NUMERIC_ROLES = {
    "brightness_percent",
    "color_temp_percent",
    "fan_speed_percent",
    "position_percent",
    "temperature_c",
    "target_temperature_c",
}


def _is_text_point(point: PointProfile) -> bool:
    return point.data_type == "string" or point.enum_values is not None


def _is_numeric_point(point: PointProfile) -> bool:
    return point.data_type not in {"bool", "string"} and point.enum_values is None


def _validate_fixed_command_value(point: PointProfile, value) -> None:
    if point.data_type == "bool":
        if type(value) is not bool:
            raise ValueError("fixed command value must be boolean")
        return
    if point.enum_values is not None:
        if not isinstance(value, str) or value not in point.enum_values:
            raise ValueError("fixed command value must be a reviewed enum label")
        return
    if point.data_type == "string":
        if not isinstance(value, str):
            raise ValueError("fixed command value must be a string")
        try:
            encoded = value.encode(point.string_encoding)
        except UnicodeEncodeError as exc:
            raise ValueError("fixed command value has invalid string encoding") from exc
        if len(encoded) > (point.string_length or 0):
            raise ValueError("fixed command string exceeds the point length")
        return
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError("fixed command value must be finite numeric")
    if point.minimum is not None and value < point.minimum:
        raise ValueError("fixed command value is below the point minimum")
    if point.maximum is not None and value > point.maximum:
        raise ValueError("fixed command value is above the point maximum")


class CompositeCommand(BaseModel):
    point_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    argument: CompositeArgument | None = None
    value: bool | int | float | str | None = None

    @field_validator("value")
    @classmethod
    def finite_value(cls, value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("composite command value must be finite")
        return value

    @model_validator(mode="after")
    def argument_or_fixed_value(self):
        if (self.argument is None) == (self.value is None):
            raise ValueError("composite command requires exactly one of argument or value")
        return self


class CompositeProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=100)
    entity_type: CompositeEntityType
    state_points: dict[str, str] = Field(min_length=1, max_length=12)
    commands: dict[str, CompositeCommand] = Field(default_factory=dict, max_length=12)

    @model_validator(mode="after")
    def valid_roles_and_commands(self):
        unsupported_roles = set(self.state_points) - STATE_ROLES[self.entity_type]
        if unsupported_roles:
            raise ValueError(
                f"unsupported {self.entity_type} state roles: {sorted(unsupported_roles)}"
            )
        expected_commands = COMMAND_ARGUMENTS[self.entity_type]
        unsupported_commands = set(self.commands) - set(expected_commands)
        if unsupported_commands:
            raise ValueError(
                f"unsupported {self.entity_type} commands: {sorted(unsupported_commands)}"
            )
        for command_name, binding in self.commands.items():
            expected_argument = expected_commands[command_name]
            if binding.argument != expected_argument:
                expected = expected_argument or "a fixed value"
                raise ValueError(f"{command_name} requires {expected}")
        return self


class PollGroupProfile(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    point_ids: list[str] = Field(min_length=1, max_length=256)
    interval_seconds: int = Field(default=15, ge=0, le=86400)
    priority: int = Field(default=0, ge=-100, le=100)

    @field_validator("point_ids")
    @classmethod
    def unique_point_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("poll group point ids must be unique")
        return value


class DeviceConfig(RuntimeConfig):
    host: str
    transport: Literal["tcp", "rtu_sidecar"] = "tcp"
    alias: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=0, le=86400)
    poll_groups: list[PollGroupProfile] = Field(default_factory=list, max_length=32)
    inter_message_delay_ms: int = Field(default=0, ge=0, le=5000)
    poll_jitter_percent: float = Field(default=10.0, ge=0, le=50, allow_inf_nan=False)
    poll_backoff_max_seconds: int = Field(default=300, ge=1, le=86400)
    service_name: str | None = None
    register_address: int | None = None
    unit_id: int | None = None
    serial_port: str | None = None
    baud_rate: int = Field(default=9600, ge=1200, le=921600)
    parity: Literal["N", "E", "O"] = "N"
    stop_bits: Literal[1, 2] = 1
    data_bits: Literal[7, 8] = 8
    response_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    profile_id: str = Field(default="inline-profile", pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    profile_version: str = Field(default="1.0.0", min_length=1, max_length=64)
    profile_provenance: str = Field(default="user-reviewed", min_length=1, max_length=200)
    points: list[PointProfile] = Field(default_factory=list, max_length=256)
    composites: list[CompositeProfile] = Field(default_factory=list, max_length=64)

    @field_validator("points")
    @classmethod
    def valid_points(cls, value: list[PointProfile]) -> list[PointProfile]:
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

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "rtu_sidecar":
            if not self.serial_port or not self.points:
                raise ValueError("rtu_sidecar requires serial_port and points")
        point_by_id = {point.id: point for point in self.points}
        group_ids = [group.id for group in self.poll_groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("poll group ids must be unique")
        grouped_points: set[str] = set()
        for group in self.poll_groups:
            unknown = set(group.point_ids) - set(point_by_id)
            if unknown:
                raise ValueError(
                    f"poll group {group.id} references unknown points: {sorted(unknown)}"
                )
            duplicate = grouped_points & set(group.point_ids)
            if duplicate:
                raise ValueError(
                    f"points may belong to only one poll group: {sorted(duplicate)}"
                )
            grouped_points.update(group.point_ids)
        composite_ids = [composite.id for composite in self.composites]
        if len(composite_ids) != len(set(composite_ids)):
            raise ValueError("composite ids must be unique")
        if set(composite_ids) & set(point_by_id):
            raise ValueError("composite ids must not match point ids")
        for composite in self.composites:
            references = set(composite.state_points.values()) | {
                binding.point_id for binding in composite.commands.values()
            }
            missing = references - set(point_by_id)
            if missing:
                raise ValueError(
                    f"composite {composite.id} references unknown points: {sorted(missing)}"
                )
            for role, point_id in composite.state_points.items():
                point = point_by_id[point_id]
                compatible = (
                    role in BOOLEAN_ROLES
                    and point.data_type == "bool"
                    or role in TEXT_ROLES
                    and _is_text_point(point)
                    or role in NUMERIC_ROLES
                    and _is_numeric_point(point)
                )
                if not compatible:
                    raise ValueError(
                        f"composite state role {role} has an incompatible point type"
                    )
            for command_name, binding in composite.commands.items():
                point = point_by_id[binding.point_id]
                if not point.writable:
                    raise ValueError(
                        f"composite command {command_name} requires a writable point"
                    )
                if binding.argument == "mode" and not _is_text_point(point):
                    raise ValueError("mode command requires an enum or string point")
                if binding.argument == "oscillating" and point.data_type != "bool":
                    raise ValueError("oscillating command requires a boolean point")
                if binding.argument not in {None, "mode", "oscillating"} and not _is_numeric_point(point):
                    raise ValueError(
                        f"{binding.argument} command requires a numeric point"
                    )
                if binding.argument is None:
                    _validate_fixed_command_value(point, binding.value)
        return self
