"""Normalize Bambu LAN MQTT print reports without retaining private job metadata."""

from __future__ import annotations

from math import isfinite
from typing import Any


def _number(value: Any, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(result) or not minimum <= result <= maximum:
        return None
    return result


def _integer(value: Any, *, minimum: int, maximum: int) -> int | None:
    number = _number(value, minimum=minimum, maximum=maximum)
    if number is None or not number.is_integer():
        return None
    return int(number)


def normalize_print_report(
    payload: dict[str, Any], previous: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Merge X1 full and P1 delta reports; return None for unrelated messages."""
    report = payload.get("print")
    if not isinstance(report, dict) or report.get("command") != "push_status":
        return None
    state = dict(previous or {})
    touched = False

    raw_status = report.get("gcode_state")
    if isinstance(raw_status, str) and 1 <= len(raw_status) <= 32 and raw_status.isascii() and raw_status.replace("_", "").isalnum():
        state["print_status"] = raw_status.upper()
        touched = True

    numeric_fields = {
        "mc_percent": ("print_progress_percent", 0, 100, False),
        "mc_remaining_time": ("remaining_time_minutes", 0, 10080, False),
        "layer_num": ("current_layer", 0, 100000, True),
        "total_layer_num": ("total_layers", 0, 100000, True),
        "nozzle_temper": ("nozzle_temperature_c", -40, 500, False),
        "nozzle_target_temper": ("target_nozzle_temperature_c", 0, 500, False),
        "bed_temper": ("bed_temperature_c", -40, 200, False),
        "bed_target_temper": ("target_bed_temperature_c", 0, 200, False),
    }
    for key, (name, minimum, maximum, integer) in numeric_fields.items():
        if key not in report:
            continue
        value = (
            _integer(report[key], minimum=minimum, maximum=maximum)
            if integer
            else _number(report[key], minimum=minimum, maximum=maximum)
        )
        if value is not None:
            state[name] = value
            touched = True
    if not touched:
        return None
    state["connected"] = True
    return state
