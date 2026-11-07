from __future__ import annotations

import hashlib
import json
import re
from typing import Any


REFRIGERATOR_DEVICE_TYPES = {
    "DEVICE_REFRIGERATOR",
}

_SENSITIVE_PATH_PARTS = {
    "access_token",
    "authorization",
    "certificate",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "subscription_topic",
    "token",
}

_KNOWN_PROPERTY_TOKENS = {
    "connected",
    "door_state",
    "eco_friendly_mode",
    "express_fridge",
    "express_mode",
    "express_mode_name",
    "fresh_air_filter",
    "fresh_air_filter_remain_percent",
    "location_name",
    "notification",
    "online",
    "power_save_enabled",
    "rapid_freeze",
    "sabbath_mode",
    "target_temperature",
    "target_temperature_c",
    "target_temperature_f",
    "temperature_unit",
    "unit",
    "used_time",
    "water_filter_1_remain_percent",
    "water_filter_2_remain_percent",
    "water_filter_3_remain_percent",
    "water_filter1_remain_percent",
    "water_filter2_remain_percent",
    "water_filter3_remain_percent",
    "water_filter_state",
}


def _token(value: Any) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _mapping_value(mapping: Any, *names: str) -> Any:
    if not isinstance(mapping, dict):
        return None
    wanted = {_token(name) for name in names}
    for key, value in mapping.items():
        if _token(key) in wanted:
            return value
    return None


def _resource(status: dict[str, Any], *names: str) -> Any:
    return _mapping_value(status, *names)


def _property(status: dict[str, Any], resource_names: tuple[str, ...], *property_names: str) -> Any:
    resource = _resource(status, *resource_names)
    value = _mapping_value(resource, *property_names)
    if value is not None:
        return value
    return _mapping_value(status, *property_names)


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value in {0, 1}:
            return bool(value)
        return None
    normalized = _token(value)
    if normalized in {"on", "open", "true", "enabled", "enable", "active", "yes"}:
        return True
    if normalized in {"off", "closed", "false", "disabled", "disable", "inactive", "no"}:
        return False
    return None


def _unit(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in {"C", "°C"}:
        return "°C"
    if normalized in {"F", "°F"}:
        return "°F"
    return None


def _temperature_value(item: dict[str, Any]) -> tuple[float | int, str] | None:
    candidates = (
        ("targetTemperature", _mapping_value(item, "unit")),
        ("targetTemperatureC", "C"),
        ("targetTemperatureF", "F"),
        ("target_temperature", _mapping_value(item, "unit")),
        ("target_temperature_c", "C"),
        ("target_temperature_f", "F"),
    )
    for key, unit_hint in candidates:
        value = _mapping_value(item, key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            resolved_unit = _unit(unit_hint)
            if resolved_unit:
                return value, resolved_unit
    return None


def _temperature_compartments(status: dict[str, Any]) -> list[dict[str, Any]]:
    by_location: dict[str, dict[str, Any]] = {}
    for resource_name in ("temperatureInUnits", "temperature"):
        collection = _resource(status, resource_name)
        if isinstance(collection, dict):
            collection = [collection]
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict):
                continue
            location = _token(_mapping_value(item, "locationName", "location")) or "main"
            temperature = _temperature_value(item)
            if temperature is None:
                continue
            value, unit = temperature
            by_location.setdefault(
                location,
                {
                    "location": location,
                    "target_temperature": value,
                    "unit": unit,
                },
            )
    return list(by_location.values())


def _doors(status: dict[str, Any]) -> list[dict[str, Any]]:
    collection = _resource(status, "doorStatus")
    if collection is None:
        scalar = _mapping_value(status, "doorState", "door_state")
        collection = [] if scalar is None else [{"locationName": "MAIN", "doorState": scalar}]
    elif isinstance(collection, dict):
        collection = [collection]
    if not isinstance(collection, list):
        return []
    doors: list[dict[str, Any]] = []
    for item in collection:
        if not isinstance(item, dict):
            continue
        state = _mapping_value(item, "doorState", "state")
        if state is None:
            continue
        doors.append(
            {
                "location": _token(_mapping_value(item, "locationName", "location")) or "main",
                "state": str(state),
                "open": _bool_value(state),
            }
        )
    return doors


def _notification(status: dict[str, Any]) -> dict[str, Any] | None:
    source = _resource(status, "notification", "event")
    if isinstance(source, list):
        source = next((item for item in reversed(source) if isinstance(item, dict)), None)
    if isinstance(source, dict):
        code = _mapping_value(source, "eventType", "event_type", "code", "type")
    else:
        code = source
    if code in {None, ""}:
        return None
    normalized = _token(code)
    known = normalized in {
        "door_is_open",
        "frozen_is_complete",
        "time_to_change_filter",
        "time_to_change_water_filter",
    }
    return {
        "code": str(code)[:120],
        "known": known,
        "severity": "warning" if normalized == "door_is_open" else "info",
    }


def _iter_scalars(value: Any, path: tuple[str, ...] = ()):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _iter_scalars(nested, (*path, _token(key)))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _iter_scalars(nested, (*path, str(index)))
    else:
        yield path, value


def _additional_readable(status: dict[str, Any]) -> list[dict[str, Any]]:
    additional: list[dict[str, Any]] = []
    for path, value in _iter_scalars(status):
        path_tokens = {part for part in path if not part.isdigit()}
        if path_tokens & _SENSITIVE_PATH_PARTS or path_tokens & _KNOWN_PROPERTY_TOKENS:
            continue
        if not isinstance(value, (str, int, float, bool)) or value is None:
            continue
        safe_value = value[:120] if isinstance(value, str) else value
        additional.append({"provider_path": ".".join(path), "value": safe_value})
        if len(additional) >= 100:
            break
    return additional


def profile_fingerprint(profile: dict[str, Any] | None) -> str | None:
    if not isinstance(profile, dict) or not profile:
        return None
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _writable_param(
    properties: Any,
    property_name: str,
) -> dict[str, Any] | None:
    spec = _mapping_value(properties, property_name)
    if not isinstance(spec, dict) or "w" not in spec.get("mode", []):
        return None
    value_spec = spec.get("value") if isinstance(spec.get("value"), dict) else {}
    writable = value_spec.get("w")
    property_type = _token(spec.get("type"))
    parameter: dict[str, Any] = {
        "name": property_name,
        "type": "boolean" if property_type == "boolean" else property_type or "string",
        "required": True,
    }
    if property_type == "boolean":
        parameter["options"] = writable if isinstance(writable, list) else [True, False]
    elif property_type in {"enum", "list"} and isinstance(writable, list):
        parameter["options"] = writable
    elif property_type == "range" and isinstance(writable, dict):
        parameter.update(
            {
                "type": "number",
                "min": writable.get("min"),
                "max": writable.get("max"),
                "step": writable.get("step", 1),
                "unit": spec.get("unit"),
            }
        )
    else:
        return None
    return parameter


def derive_refrigerator_controls(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build reviewed controls from LG profile writability, never from model name."""
    if not isinstance(profile, dict):
        return []
    properties = profile.get("property")
    if not isinstance(properties, dict):
        return []
    mappings = (
        ("powerSave", "powerSaveEnabled", "set_power_save"),
        ("ecoFriendly", "ecoFriendlyMode", "set_eco_friendly"),
        ("sabbath", "sabbathMode", "set_sabbath_mode"),
        ("refrigeration", "rapidFreeze", "set_rapid_freeze"),
        ("refrigeration", "expressMode", "set_express_mode"),
        ("refrigeration", "expressFridge", "set_express_fridge"),
    )
    controls: list[dict[str, Any]] = []
    for resource_name, property_name, method_name in mappings:
        resource = _mapping_value(properties, resource_name)
        parameter = _writable_param(resource, property_name)
        if parameter is None:
            continue
        controls.append(
            {
                "method": method_name,
                "resource": resource_name,
                "parameters": [parameter],
            }
        )
    return controls


def normalize_refrigerator_state(
    status: dict[str, Any],
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    compartments = _temperature_compartments(status)
    doors = _doors(status)
    metrics: dict[str, Any] = {}
    units: dict[str, str] = {}
    capabilities: set[str] = set()

    for compartment in compartments:
        location = compartment["location"]
        metric_id = f"{location}_target_temperature"
        metrics[metric_id] = compartment["target_temperature"]
        units[metric_id] = compartment["unit"]
        capabilities.add(metric_id)

    primary = next(
        (item for item in compartments if item["location"] == "fridge"),
        compartments[0] if compartments else None,
    )
    if primary:
        metrics["target_temperature"] = primary["target_temperature"]
        units["target_temperature"] = primary["unit"]
        capabilities.add("target_temperature")

    if doors:
        main_door = next((door for door in doors if door["location"] == "main"), doors[0])
        metrics["door"] = main_door["state"]
        capabilities.add("door")
        if main_door["open"] is not None:
            metrics["door_open"] = main_door["open"]
            capabilities.add("door_open")

    mode_specs = (
        ("power_save_enabled", ("powerSave", "power_save"), ("powerSaveEnabled", "power_save_enabled")),
        ("eco_friendly_enabled", ("ecoFriendly", "eco_friendly"), ("ecoFriendlyMode", "eco_friendly_mode")),
        ("sabbath_mode_enabled", ("sabbath",), ("sabbathMode", "sabbath_mode")),
        ("rapid_freeze_enabled", ("refrigeration",), ("rapidFreeze", "rapid_freeze")),
        ("express_mode_enabled", ("refrigeration",), ("expressMode", "express_mode")),
        ("express_fridge_enabled", ("refrigeration",), ("expressFridge", "express_fridge")),
    )
    modes: dict[str, Any] = {}
    for metric_id, resource_names, property_names in mode_specs:
        raw_value = _property(status, resource_names, *property_names)
        value = _bool_value(raw_value)
        if value is None:
            continue
        metrics[metric_id] = value
        modes[metric_id] = value
        capabilities.add(metric_id)

    refrigeration = _resource(status, "refrigeration")
    fresh_air_mode = _mapping_value(refrigeration, "freshAirFilter", "fresh_air_filter")
    fresh_air_life = _mapping_value(
        refrigeration,
        "freshAirFilterRemainPercent",
        "fresh_air_filter_remain_percent",
    )
    filters: list[dict[str, Any]] = []
    if fresh_air_mode is not None or isinstance(fresh_air_life, (int, float)):
        fresh_air: dict[str, Any] = {"id": "fresh_air", "type": "fresh_air"}
        if fresh_air_mode is not None:
            fresh_air["state"] = fresh_air_mode
            metrics["fresh_air_filter_mode"] = fresh_air_mode
            capabilities.add("fresh_air_filter_mode")
        if isinstance(fresh_air_life, (int, float)) and not isinstance(fresh_air_life, bool):
            fresh_air["remaining_percent"] = fresh_air_life
            metrics["fresh_air_filter_life"] = fresh_air_life
            units["fresh_air_filter_life"] = "%"
            capabilities.add("fresh_air_filter_life")
        filters.append(fresh_air)

    water = _resource(status, "waterFilterInfo", "water_filter_info")
    water_state = _mapping_value(water, "waterFilterState", "water_filter_state")
    used_time = _mapping_value(water, "usedTime", "used_time")
    used_time_unit = _mapping_value(water, "unit")
    for index in (1, 2, 3):
        remaining = _mapping_value(
            water,
            f"waterFilter{index}RemainPercent",
            f"water_filter_{index}_remain_percent",
        )
        if remaining is None and index > 1:
            continue
        if remaining is None and water_state is None and used_time is None:
            continue
        water_filter: dict[str, Any] = {"id": f"water_{index}", "type": "water"}
        if water_state is not None:
            water_filter["state"] = water_state
        if isinstance(remaining, (int, float)) and not isinstance(remaining, bool):
            water_filter["remaining_percent"] = remaining
            metric_id = f"water_filter_{index}_life"
            metrics[metric_id] = remaining
            units[metric_id] = "%"
            capabilities.add(metric_id)
        if used_time is not None:
            water_filter["used_time"] = used_time
            water_filter["used_time_unit"] = used_time_unit
        filters.append(water_filter)
    if water_state is not None:
        metrics["water_filter_state"] = water_state
        capabilities.add("water_filter_state")

    remaining_values = [
        item["remaining_percent"]
        for item in filters
        if isinstance(item.get("remaining_percent"), (int, float))
        and not isinstance(item.get("remaining_percent"), bool)
    ]
    if remaining_values:
        metrics["filter_life"] = min(remaining_values)
        units["filter_life"] = "%"
        capabilities.add("filter_life")

    latest_notification = _notification(status)
    if latest_notification:
        metrics["notification"] = latest_notification["code"]
        capabilities.add("notification")

    return {
        "metrics": metrics,
        "units": units,
        "capabilities": sorted(capabilities),
        "details": {
            "compartments": compartments,
            "doors": doors,
            "modes": modes,
            "filters": filters,
            "notification": latest_notification,
            "additional_capabilities": _additional_readable(status),
        },
        "profile_fingerprint": profile_fingerprint(profile),
    }
