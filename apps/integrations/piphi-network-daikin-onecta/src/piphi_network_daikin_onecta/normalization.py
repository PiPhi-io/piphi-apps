from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any


def _value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) and "value" in value else value


def _number(value: Any) -> float | None:
    value = _value(value)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
    ):
        return None
    return float(value)


def _text(value: Any) -> str | None:
    value = _value(value)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _boolean(value: Any, default: bool = False) -> bool:
    value = _value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return default


def opaque_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ClimatePoint:
    device_id: str
    gateway_id: str
    management_point_id: str
    name: str
    model: str | None
    connected: bool
    power: bool | None
    hvac_mode: str | None
    indoor_temperature_c: float | None
    target_temperature_c: float | None
    target_temperature_min_c: float | None
    target_temperature_max_c: float | None
    target_temperature_step_c: float | None
    target_path: str | None
    target_settable: bool


def normalize_devices(
    subject: str, devices: tuple[dict[str, Any], ...]
) -> list[ClimatePoint]:
    result: list[ClimatePoint] = []
    for gateway in devices:
        gateway_id = _text(gateway.get("id"))
        if gateway_id is None:
            continue
        model = _text(gateway.get("deviceModel")) or _text(gateway.get("model"))
        points = gateway.get("managementPoints")
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, dict):
                continue
            point_id = _text(point.get("embeddedId")) or _text(point.get("id"))
            if point_id is None:
                continue
            mode = _text(point.get("operationMode"))
            indoor = _number(point.get("roomTemperature"))
            control = point.get("temperatureControl")
            operation_modes = _value(control)
            if isinstance(operation_modes, dict):
                operation_modes = operation_modes.get("operationModes", operation_modes)
            mode_control = (
                operation_modes.get(mode)
                if isinstance(operation_modes, dict) and mode
                else None
            )
            setpoints = (
                mode_control.get("setpoints")
                if isinstance(mode_control, dict)
                else None
            )
            target = (
                setpoints.get("roomTemperature")
                if isinstance(setpoints, dict)
                else None
            )
            if indoor is None and target is None:
                continue
            target_value = _number(target)
            target_path = None
            target_settable = False
            minimum = maximum = step = None
            if isinstance(target, dict):
                target_settable = bool(target.get("settable", False))
                minimum = _number(target.get("minValue"))
                maximum = _number(target.get("maxValue"))
                step = _number(target.get("stepValue"))
                target_path = (
                    f"/operationModes/{mode}/setpoints/roomTemperature"
                    if mode
                    else None
                )
            result.append(
                ClimatePoint(
                    device_id=opaque_id(subject, gateway_id, point_id),
                    gateway_id=gateway_id,
                    management_point_id=point_id,
                    name=_text(point.get("name"))
                    or _text(gateway.get("name"))
                    or "Daikin climate",
                    model=model,
                    connected=_boolean(point.get("isCloudConnectionUp"), default=True),
                    power={"on": True, "off": False}.get(
                        _text(point.get("onOffMode")) or ""
                    ),
                    hvac_mode=mode,
                    indoor_temperature_c=indoor,
                    target_temperature_c=target_value,
                    target_temperature_min_c=minimum,
                    target_temperature_max_c=maximum,
                    target_temperature_step_c=step,
                    target_path=target_path,
                    target_settable=target_settable and target_path is not None,
                )
            )
    return result
