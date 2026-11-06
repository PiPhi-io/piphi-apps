from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Iterable
from typing import Any


CLIENT_ID_NAMESPACE = uuid.UUID("2bea399e-5cf7-41e7-8652-70c1fb44cff7")

DEVICE_TYPE_CATALOG: dict[str, dict[str, Any]] = {
    "DEVICE_AIR_CONDITIONER": {
        "resources": ["operation", "temperature", "air_flow", "air_quality_sensor", "filter_info", "display", "wind_direction"],
        "properties": [
            "current_temperature_c",
            "target_temperature_c",
            "humidity",
            "wind_strength",
            "pm1",
            "pm2",
            "pm10",
            "filter_remain_percent",
            "display_light",
        ],
        "capabilities": ["switch", "temperature", "target_temperature", "humidity", "pm1", "pm2", "pm10", "mode", "fan_speed", "filter_life", "brightness"],
        "device_class": "climate",
        "entity_type": "thermostat",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_target_temperature", "set_fan_speed", "set_brightness"],
    },
    "DEVICE_AIR_PURIFIER": {
        "resources": ["operation", "air_flow", "air_quality_sensor", "filter_info", "timer"],
        "properties": ["wind_strength", "pm1", "pm2", "pm10", "humidity", "filter_remain_percent", "top_filter_remain_percent"],
        "capabilities": ["switch", "humidity", "pm1", "pm2", "pm10", "mode", "fan_speed", "filter_life"],
        "device_class": "air-treatment",
        "entity_type": "sensor",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_fan_speed"],
    },
    "DEVICE_AIR_PURIFIER_FAN": {
        "resources": ["operation", "air_flow", "air_quality_sensor", "display", "misc", "timer", "sleep_timer"],
        "properties": ["wind_strength", "wind_temperature", "pm1", "pm2", "pm10", "humidity", "temperature", "display_light"],
        "capabilities": ["switch", "temperature", "humidity", "pm1", "pm2", "pm10", "mode", "fan_speed", "brightness"],
        "device_class": "air-treatment",
        "entity_type": "sensor",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_fan_speed", "set_brightness"],
    },
    "DEVICE_CEILING_FAN": {
        "resources": ["air_flow", "operation"],
        "properties": ["wind_strength", "ceiling_fan_operation_mode"],
        "capabilities": ["switch", "fan_speed", "mode"],
        "device_class": "fan",
        "entity_type": "device",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_fan_speed", "set_mode"],
    },
    "DEVICE_COOKTOP": {
        "resources": ["operation", "cooking_zone", "power", "remote_control_enable", "timer"],
        "properties": ["operation_mode", "current_state", "power_level", "remote_control_enabled", "remain_hour", "remain_minute"],
        "capabilities": ["switch", "power", "mode"],
        "device_class": "kitchen",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode"],
    },
    "DEVICE_DEHUMIDIFIER": {
        "resources": ["operation", "dehumidifier_job_mode", "humidity", "air_flow"],
        "properties": ["current_humidity", "target_humidity", "wind_strength"],
        "capabilities": ["switch", "humidity", "mode", "fan_speed"],
        "device_class": "air-treatment",
        "entity_type": "sensor",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_fan_speed", "set_target_humidity"],
    },
    "DEVICE_DISH_WASHER": {
        "resources": ["run_state", "door_status", "operation", "remote_control_enable", "timer", "dish_washing_course"],
        "properties": ["current_state", "door_state", "dish_washer_operation_mode", "remote_control_enabled", "remain_hour", "remain_minute", "current_dish_washing_course"],
        "capabilities": ["switch", "door", "mode"],
        "device_class": "laundry",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_course", "enable_remote_control", "disable_remote_control"],
    },
    "DEVICE_DRYER": {
        "resources": ["run_state", "operation", "remote_control_enable", "timer"],
        "properties": ["current_state", "dryer_operation_mode", "remote_control_enabled", "remain_hour", "remain_minute"],
        "capabilities": ["switch", "mode"],
        "device_class": "laundry",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_course", "enable_remote_control", "disable_remote_control"],
    },
    "DEVICE_HOME_BREW": {
        "resources": ["run_state", "recipe", "timer"],
        "properties": ["current_state", "beer_remain", "recipe_name", "elapsed_day_state", "elapsed_day_total"],
        "capabilities": ["mode"],
        "device_class": "kitchen",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_course"],
    },
    "DEVICE_HOOD": {
        "resources": ["ventilation", "lamp", "operation"],
        "properties": ["fan_speed", "lamp_brightness", "hood_operation_mode"],
        "capabilities": ["switch", "fan_speed", "brightness", "mode"],
        "device_class": "kitchen",
        "entity_type": "device",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_fan_speed", "set_brightness", "set_mode"],
    },
    "DEVICE_HUMIDIFIER": {
        "resources": ["humidifier_job_mode", "operation", "humidity", "air_flow", "air_quality_sensor", "display", "mood_lamp", "timer", "sleep_timer"],
        "properties": ["target_humidity", "wind_strength", "pm1", "pm2", "pm10", "humidity", "temperature", "display_light", "mood_lamp_state"],
        "capabilities": ["switch", "temperature", "humidity", "pm1", "pm2", "pm10", "mode", "fan_speed", "brightness"],
        "device_class": "air-treatment",
        "entity_type": "sensor",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_fan_speed", "set_target_humidity", "set_brightness"],
    },
    "DEVICE_KIMCHI_REFRIGERATOR": {
        "resources": ["refrigeration", "temperature"],
        "properties": ["one_touch_filter", "fresh_air_filter", "target_temperature"],
        "capabilities": ["target_temperature", "filter_life"],
        "device_class": "refrigeration",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "set_target_temperature"],
    },
    "DEVICE_MICROWAVE_OVEN": {
        "resources": ["run_state", "timer", "ventilation", "lamp"],
        "properties": ["current_state", "remain_minute", "remain_second", "fan_speed", "lamp_brightness"],
        "capabilities": ["fan_speed", "brightness", "mode"],
        "device_class": "kitchen",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "set_fan_speed", "set_brightness"],
    },
    "DEVICE_OVEN": {
        "resources": ["run_state", "operation", "cook", "remote_control_enable", "temperature", "timer"],
        "properties": ["oven_type", "current_state", "oven_operation_mode", "cook_mode", "remote_control_enabled", "target_temperature_c"],
        "capabilities": ["switch", "temperature", "target_temperature", "mode"],
        "device_class": "kitchen",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_cook_mode", "set_target_temperature"],
    },
    "DEVICE_PLANT_CULTIVATOR": {
        "resources": ["run_state", "light", "temperature"],
        "properties": ["current_state", "growth_mode", "wind_volume", "brightness", "duration", "day_target_temperature", "night_target_temperature", "temperature_state"],
        "capabilities": ["temperature", "target_temperature", "brightness", "mode"],
        "device_class": "device",
        "entity_type": "device",
        "documented_commands": ["refresh", "set_mode", "set_brightness", "set_target_temperature"],
    },
    "DEVICE_REFRIGERATOR": {
        "resources": ["power_save", "eco_friendly", "sabbath", "refrigeration", "water_filter_info", "door_status", "temperature"],
        "properties": ["power_save_enabled", "eco_friendly_mode", "rapid_freeze", "express_mode", "fresh_air_filter", "fresh_air_filter_remain_percent", "water_filter_state", "water_filter_1_remain_percent", "door_state", "target_temperature_c"],
        "capabilities": ["door", "target_temperature", "filter_life", "mode"],
        "device_class": "refrigeration",
        "entity_type": "appliance",
        "documented_commands": [
            "refresh",
            "set_target_temperature",
            "enable_power_save",
            "disable_power_save",
            "enable_eco_friendly",
            "disable_eco_friendly",
            "enable_express_mode",
            "disable_express_mode",
            "enable_rapid_freeze",
            "disable_rapid_freeze",
            "enable_sabbath_mode",
            "disable_sabbath_mode",
        ],
    },
    "DEVICE_ROBOT_CLEANER": {
        "resources": ["run_state", "robot_cleaner_job_mode", "operation", "battery", "timer"],
        "properties": ["current_state", "current_job_mode", "clean_operation_mode", "battery_level", "battery_percent", "running_hour", "running_minute"],
        "capabilities": ["switch", "battery", "mode"],
        "device_class": "vacuum",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_mode"],
    },
    "DEVICE_STICK_CLEANER": {
        "resources": ["run_state", "stick_cleaner_job_mode", "battery"],
        "properties": ["current_state", "current_job_mode", "battery_level", "battery_percent"],
        "capabilities": ["battery", "mode"],
        "device_class": "vacuum",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "set_mode"],
    },
    "DEVICE_STYLER": {
        "resources": ["run_state", "operation", "remote_control_enable", "timer"],
        "properties": ["current_state", "styler_operation_mode", "remote_control_enabled", "remain_hour", "remain_minute", "total_hour", "total_minute"],
        "capabilities": ["switch", "mode"],
        "device_class": "laundry",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_course", "enable_remote_control", "disable_remote_control"],
    },
    "DEVICE_SYSTEM_BOILER": {
        "resources": ["boiler_job_mode", "operation", "hot_water_temperature", "room_temperature"],
        "properties": ["boiler_operation_mode", "hot_water_mode", "room_temp_mode", "room_water_mode", "hot_water_current_temperature_c", "hot_water_target_temperature_c", "room_current_temperature_c"],
        "capabilities": ["switch", "temperature", "target_temperature", "mode"],
        "device_class": "climate",
        "entity_type": "thermostat",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_target_temperature"],
    },
    "DEVICE_WASHER": {
        "resources": ["run_state", "operation", "remote_control_enable", "timer", "detergent", "cycle"],
        "properties": ["current_state", "washer_operation_mode", "remote_control_enabled", "remain_hour", "remain_minute", "cycle_count"],
        "capabilities": ["switch", "mode"],
        "device_class": "laundry",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "start", "pause", "stop", "set_course", "enable_remote_control", "disable_remote_control"],
    },
    "DEVICE_WATER_HEATER": {
        "resources": ["water_heater_job_mode", "operation", "temperature"],
        "properties": ["water_heater_operation_mode", "current_temperature_c", "target_temperature_c", "temperature_unit"],
        "capabilities": ["switch", "temperature", "target_temperature", "mode"],
        "device_class": "climate",
        "entity_type": "thermostat",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_target_temperature"],
    },
    "DEVICE_WATER_PURIFIER": {
        "resources": ["run_state", "water_info"],
        "properties": ["cock_state", "sterilizing_state", "water_type"],
        "capabilities": ["mode"],
        "device_class": "device",
        "entity_type": "device",
        "documented_commands": ["refresh", "set_mode"],
    },
    "DEVICE_WINE_CELLAR": {
        "resources": ["operation", "temperature"],
        "properties": ["light_brightness", "optimal_humidity", "sabbath_mode", "light_status", "target_temperature_c"],
        "capabilities": ["brightness", "humidity", "target_temperature", "mode"],
        "device_class": "refrigeration",
        "entity_type": "appliance",
        "documented_commands": ["refresh", "set_brightness", "set_target_temperature", "set_mode"],
    },
    "DEVICE_VENTILATOR": {
        "resources": ["ventilator_job_mode", "operation", "temperature", "air_quality_sensor", "air_flow", "timer", "sleep_timer"],
        "properties": ["current_temperature", "pm1", "pm2", "pm10", "co2", "wind_strength"],
        "capabilities": ["switch", "temperature", "pm1", "pm2", "pm10", "co2", "mode", "fan_speed"],
        "device_class": "air-treatment",
        "entity_type": "sensor",
        "documented_commands": ["refresh", "turn_on", "turn_off", "toggle", "set_mode", "set_fan_speed"],
    },
}

SPECIAL_TOGGLE_COMMAND_SPECS: tuple[dict[str, Any], ...] = (
    {
        "match_tokens": ("power_save",),
        "enable_id": "enable_power_save",
        "disable_id": "disable_power_save",
        "label": "Power Save",
    },
    {
        "match_tokens": ("eco_friendly", "eco"),
        "enable_id": "enable_eco_friendly",
        "disable_id": "disable_eco_friendly",
        "label": "Eco Friendly",
    },
    {
        "match_tokens": ("sabbath",),
        "enable_id": "enable_sabbath_mode",
        "disable_id": "disable_sabbath_mode",
        "label": "Sabbath Mode",
    },
    {
        "match_tokens": ("express_mode", "express"),
        "enable_id": "enable_express_mode",
        "disable_id": "disable_express_mode",
        "label": "Express Mode",
    },
    {
        "match_tokens": ("rapid_freeze", "express_fridge", "one_touch_filter"),
        "enable_id": "enable_rapid_freeze",
        "disable_id": "disable_rapid_freeze",
        "label": "Rapid Freeze",
    },
    {
        "match_tokens": ("remote_control",),
        "enable_id": "enable_remote_control",
        "disable_id": "disable_remote_control",
        "label": "Remote Control",
    },
)


def stable_client_id(*, access_token: str, country_code: str, device_id: str | None = None) -> str:
    token_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
    payload = "|".join(
        [
            country_code.strip().upper(),
            token_hash,
        ]
    )
    return str(uuid.uuid5(CLIENT_ID_NAMESPACE, payload))


def slugify_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token


def normalize_discovered_device(raw_device: dict[str, Any]) -> dict[str, Any]:
    device_info = (
        raw_device.get("deviceInfo")
        if isinstance(raw_device.get("deviceInfo"), dict)
        else {}
    )
    device_id = (
        raw_device.get("deviceId")
        or raw_device.get("device_id")
        or raw_device.get("id")
    )
    device_type = (
        raw_device.get("deviceType")
        or raw_device.get("device_type")
        or raw_device.get("type")
        or device_info.get("deviceType")
        or device_info.get("device_type")
        or "unknown"
    )
    device_name = (
        raw_device.get("alias")
        or raw_device.get("deviceName")
        or raw_device.get("device_name")
        or raw_device.get("name")
        or device_info.get("alias")
        or device_info.get("deviceName")
        or device_info.get("device_name")
        or device_id
    )
    return {
        "id": str(device_id),
        "device_id": str(device_id),
        "device_name": str(device_name),
        "name": str(device_name),
        "device_type": str(device_type),
        "model": raw_device.get("modelName")
        or raw_device.get("model_name")
        or device_info.get("modelName")
        or device_info.get("model_name"),
        "model_id": raw_device.get("modelJsonUrl")
        or raw_device.get("model_id")
        or device_info.get("modelJsonUrl")
        or device_info.get("model_id"),
        "platform_type": raw_device.get("platformType")
        or raw_device.get("platform_type")
        or device_info.get("platformType")
        or device_info.get("platform_type"),
        "raw": raw_device,
    }


def device_type_catalog(device_type: Any) -> dict[str, Any]:
    return DEVICE_TYPE_CATALOG.get(str(device_type or "").strip().upper(), {})


def documented_command_ids(capabilities: list[str]) -> list[str]:
    commands = ["refresh"]
    capability_set = set(capabilities)
    if "switch" in capability_set:
        commands.extend(["turn_on", "turn_off", "toggle"])
    if "mode" in capability_set:
        commands.append("set_mode")
    if "target_temperature" in capability_set:
        commands.append("set_target_temperature")
    if "fan_speed" in capability_set:
        commands.append("set_fan_speed")
    if "brightness" in capability_set:
        commands.append("set_brightness")
    seen: set[str] = set()
    return [command for command in commands if not (command in seen or seen.add(command))]


def _append_command(
    available_commands: list[dict[str, Any]],
    *,
    command_id: str,
    label: str,
    kind: str,
    description: str,
    args_schema: dict[str, Any] | None = None,
) -> None:
    available_commands.append(
        {
            "id": command_id,
            "label": label,
            "kind": kind,
            "description": description,
            "args_schema": args_schema or {},
        }
    )


def _iter_scalars(value: Any, *, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_key = slugify_token(key)
            next_path = f"{path}_{nested_key}".strip("_")
            yield from _iter_scalars(nested_value, path=next_path)
        return
    if isinstance(value, list):
        for index, nested_value in enumerate(value):
            next_path = f"{path}_{index}".strip("_")
            yield from _iter_scalars(nested_value, path=next_path)
        return
    yield path or "value", value


def _infer_unit(metric_name: str) -> str | None:
    token = metric_name.lower()
    if token.endswith("_temperature_c") or token.endswith("_temp_c") or token.endswith("_c"):
        return "°C"
    if token.endswith("_temperature_f") or token.endswith("_temp_f") or token.endswith("_f"):
        return "°F"
    if "humidity" in token or "percent" in token or "brightness" in token or "battery" in token:
        return "%"
    if "power" in token:
        return "W"
    if "energy" in token or token.endswith("_kwh"):
        return "kWh"
    if token.endswith("pm1") or token.endswith("pm2") or token.endswith("pm10"):
        return "µg/m³"
    if "co2" in token:
        return "ppm"
    if "minute" in token:
        return "min"
    if "hour" in token:
        return "h"
    return None


def _extract_metrics(raw_status: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    metrics: dict[str, Any] = {}
    units: dict[str, str] = {}
    for path, value in _iter_scalars(raw_status):
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        metrics[path] = value
        unit = _infer_unit(path)
        if unit:
            units[path] = unit
    return metrics, units


def _primary_target_temperature(
    raw_status: dict[str, Any],
) -> tuple[float | int, str] | None:
    for collection_key in ("temperature", "temperatureInUnits"):
        collection = raw_status.get(collection_key)
        if not isinstance(collection, list):
            continue
        compartments = [item for item in collection if isinstance(item, dict)]
        primary = next(
            (
                item
                for item in compartments
                if slugify_token(item.get("locationName")) == "fridge"
            ),
            compartments[0] if compartments else None,
        )
        if primary is None:
            continue
        candidates = (
            ("targetTemperature", primary.get("unit")),
            ("targetTemperatureC", "C"),
            ("targetTemperatureF", "F"),
        )
        for key, unit_value in candidates:
            value = primary.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            unit = str(unit_value or "").strip().upper()
            if unit in {"C", "°C"}:
                return value, "°C"
            if unit in {"F", "°F"}:
                return value, "°F"
    return None


def _observed_profile_terms(raw_status: dict[str, Any], raw_profile: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    resources: set[str] = set()
    properties: set[str] = set()
    for path, _value in _iter_scalars(raw_status):
        if not path:
            continue
        properties.add(path)
        resources.add(path.split("_", 1)[0])
    if isinstance(raw_profile, dict):
        for path, scalar in _iter_scalars(raw_profile):
            if path:
                properties.add(path)
                resources.add(path.split("_", 1)[0])
            if isinstance(scalar, str):
                token = slugify_token(scalar)
                if token:
                    resources.add(token)
    return sorted(resources), sorted(properties)


def _collect_search_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for path, scalar in _iter_scalars(value):
            if path:
                tokens.update(part for part in path.split("_") if part)
            if isinstance(scalar, str):
                normalized = slugify_token(scalar)
                tokens.update(part for part in normalized.split("_") if part)
    return tokens


def _normalize_params(raw_params: Any) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    if isinstance(raw_params, dict):
        for key, spec in raw_params.items():
            normalized[slugify_token(key)] = _coerce_param_spec(key, spec)
    elif isinstance(raw_params, list):
        for item in raw_params:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("id") or item.get("key")
            if not name:
                continue
            normalized[slugify_token(name)] = _coerce_param_spec(name, item)
    return normalized


def _coerce_param_spec(name: Any, raw_spec: Any) -> dict[str, Any]:
    if not isinstance(raw_spec, dict):
        return {"type": "string", "label": str(name), "required": False, "options": []}
    options = raw_spec.get("options") or raw_spec.get("enum") or raw_spec.get("values") or []
    if not isinstance(options, list):
        options = []
    minimum = raw_spec.get("minimum")
    if minimum is None:
        minimum = raw_spec.get("min")
    maximum = raw_spec.get("maximum")
    if maximum is None:
        maximum = raw_spec.get("max")
    resolved_type = raw_spec.get("type")
    if not resolved_type and options:
        if all(isinstance(option, bool) for option in options):
            resolved_type = "boolean"
        elif all(isinstance(option, int) and not isinstance(option, bool) for option in options):
            resolved_type = "integer"
        elif all(isinstance(option, (int, float)) and not isinstance(option, bool) for option in options):
            resolved_type = "number"
    if not resolved_type:
        resolved_type = "number" if isinstance(raw_spec.get("default"), (int, float)) else "string"
    return {
        "type": resolved_type,
        "label": raw_spec.get("label") or str(name).replace("_", " ").title(),
        "required": bool(raw_spec.get("required", False)),
        "default": raw_spec.get("default"),
        "minimum": minimum,
        "maximum": maximum,
        "step": raw_spec.get("step"),
        "unit": raw_spec.get("unit"),
        "options": options,
    }


def _extract_control_entries(raw_controls: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            method_name = value.get("control_method") or value.get("method") or value.get("id") or value.get("name")
            if method_name:
                entries.append(
                    {
                        "method_id": str(method_name),
                        "label": value.get("label") or value.get("name") or str(method_name),
                        "params": _normalize_params(
                            value.get("params")
                            or value.get("parameters")
                            or value.get("control_params")
                            or value.get("parameter")
                        ),
                    }
                )
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(raw_controls)
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        key = slugify_token(entry["method_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _param_with_options(params: dict[str, dict[str, Any]], *, contains: tuple[str, ...] = ()) -> tuple[str, dict[str, Any]] | None:
    for name, spec in params.items():
        if contains and not any(token in name for token in contains):
            continue
        options = spec.get("options") or []
        if options:
            return name, spec
    return None


def _numeric_param(params: dict[str, dict[str, Any]], *, contains: tuple[str, ...] = ()) -> tuple[str, dict[str, Any]] | None:
    for name, spec in params.items():
        if contains and not any(token in name for token in contains):
            continue
        if spec.get("type") in {"number", "integer"}:
            return name, spec
    for name, spec in params.items():
        if spec.get("minimum") is not None or spec.get("maximum") is not None:
            return name, spec
    return None


def _enum_param_with_toggle_values(params: dict[str, dict[str, Any]]) -> tuple[str, Any, Any] | None:
    for name, spec in params.items():
        options = spec.get("options") or []
        normalized_options = {str(option).upper(): option for option in options}
        truthy = next((normalized_options[key] for key in ("ON", "ENABLE", "ENABLED", "TRUE", "START") if key in normalized_options), None)
        falsy = next((normalized_options[key] for key in ("OFF", "DISABLE", "DISABLED", "FALSE", "STOP") if key in normalized_options), None)
        if truthy is not None and falsy is not None:
            return name, truthy, falsy
    return None


def _map_turn_command(
    command_map: dict[str, dict[str, Any]],
    available_commands: list[dict[str, Any]],
    *,
    method_id: str,
    method_token: str,
    params: dict[str, dict[str, Any]],
) -> None:
    if "turn_on" in method_token or method_token.endswith("_on") or method_token == "on":
        command_map["turn_on"] = {"control_method": method_id, "control_params": {}, "arg_map": {}}
        available_commands.append(
            {
                "id": "turn_on",
                "label": "Turn On",
                "kind": "primary",
                "description": "Turn the device on.",
                "args_schema": {},
            }
        )
    if "turn_off" in method_token or method_token.endswith("_off") or method_token == "off":
        command_map["turn_off"] = {"control_method": method_id, "control_params": {}, "arg_map": {}}
        available_commands.append(
            {
                "id": "turn_off",
                "label": "Turn Off",
                "kind": "secondary",
                "description": "Turn the device off.",
                "args_schema": {},
            }
        )

    enum_param = _param_with_options(params, contains=("power", "operation", "state", "mode")) or _param_with_options(params)
    if enum_param is None:
        return
    param_name, spec = enum_param
    normalized_options = {str(option).upper(): option for option in spec.get("options") or []}
    if "ON" in normalized_options:
        command_map.setdefault(
            "turn_on",
            {
                "control_method": method_id,
                "control_params": {param_name: normalized_options["ON"]},
                "arg_map": {},
            },
        )
        available_commands.append(
            {
                "id": "turn_on",
                "label": "Turn On",
                "kind": "primary",
                "description": "Turn the device on.",
                "args_schema": {},
            }
        )
    if "OFF" in normalized_options:
        command_map.setdefault(
            "turn_off",
            {
                "control_method": method_id,
                "control_params": {param_name: normalized_options["OFF"]},
                "arg_map": {},
            },
        )
        available_commands.append(
            {
                "id": "turn_off",
                "label": "Turn Off",
                "kind": "secondary",
                "description": "Turn the device off.",
                "args_schema": {},
            }
        )
    if "turn_on" in command_map or "turn_off" in command_map:
        available_commands.append(
            {
                "id": "toggle",
                "label": "Toggle",
                "kind": "primary",
                "description": "Toggle the device power state using the latest known state.",
                "args_schema": {},
            }
        )


def _map_binary_toggle_command(
    command_map: dict[str, dict[str, Any]],
    available_commands: list[dict[str, Any]],
    *,
    method_id: str,
    method_token: str,
    params: dict[str, dict[str, Any]],
    match_tokens: tuple[str, ...],
    enable_id: str,
    disable_id: str,
    label: str,
) -> None:
    if not any(token in method_token for token in match_tokens):
        return
    toggle_param = _enum_param_with_toggle_values(params)
    if toggle_param is None:
        return
    param_name, truthy, falsy = toggle_param
    command_map.setdefault(
        enable_id,
        {
            "control_method": method_id,
            "control_params": {param_name: truthy},
            "arg_map": {},
        },
    )
    _append_command(
        available_commands,
        command_id=enable_id,
        label=f"Enable {label}",
        kind="secondary",
        description=f"Enable {label.lower()} when supported by this ThinQ profile.",
    )
    command_map.setdefault(
        disable_id,
        {
            "control_method": method_id,
            "control_params": {param_name: falsy},
            "arg_map": {},
        },
    )
    _append_command(
        available_commands,
        command_id=disable_id,
        label=f"Disable {label}",
        kind="secondary",
        description=f"Disable {label.lower()} when supported by this ThinQ profile.",
    )


def _map_exact_action_command(
    command_map: dict[str, dict[str, Any]],
    available_commands: list[dict[str, Any]],
    *,
    method_id: str,
    method_token: str,
    command_id: str,
    label: str,
    description: str,
    match_tokens: tuple[str, ...],
) -> None:
    if command_id in command_map:
        return
    if not any(token in method_token for token in match_tokens):
        return
    command_map[command_id] = {
        "control_method": method_id,
        "control_params": {},
        "arg_map": {},
    }
    _append_command(
        available_commands,
        command_id=command_id,
        label=label,
        kind="primary" if command_id == "start" else "secondary",
        description=description,
    )


def build_command_catalog(
    *,
    device_type: str,
    available_controls: Any,
    capabilities: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    available_commands: list[dict[str, Any]] = [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "secondary",
            "description": "Refresh the latest device state from LG ThinQ.",
            "args_schema": {},
        }
    ]
    command_map: dict[str, dict[str, Any]] = {}
    control_entries = _extract_control_entries(available_controls)

    for entry in control_entries:
        method_id = entry["method_id"]
        method_token = slugify_token(method_id)
        params = entry["params"]
        _map_turn_command(command_map, available_commands, method_id=method_id, method_token=method_token, params=params)
        for spec in SPECIAL_TOGGLE_COMMAND_SPECS:
            _map_binary_toggle_command(
                command_map,
                available_commands,
                method_id=method_id,
                method_token=method_token,
                params=params,
                match_tokens=spec["match_tokens"],
                enable_id=spec["enable_id"],
                disable_id=spec["disable_id"],
                label=spec["label"],
            )
        _map_exact_action_command(
            command_map,
            available_commands,
            method_id=method_id,
            method_token=method_token,
            command_id="start",
            label="Start",
            description="Start an appliance action when supported by this ThinQ profile.",
            match_tokens=("start", "resume"),
        )
        _map_exact_action_command(
            command_map,
            available_commands,
            method_id=method_id,
            method_token=method_token,
            command_id="pause",
            label="Pause",
            description="Pause an appliance action when supported by this ThinQ profile.",
            match_tokens=("pause", "hold"),
        )
        _map_exact_action_command(
            command_map,
            available_commands,
            method_id=method_id,
            method_token=method_token,
            command_id="stop",
            label="Stop",
            description="Stop an appliance action when supported by this ThinQ profile.",
            match_tokens=("stop", "cancel"),
        )

        if "mode" in method_token and "set_mode" not in command_map:
            option_param = _param_with_options(params, contains=("mode",)) or _param_with_options(params)
            if option_param is not None:
                param_name, spec = option_param
                command_map["set_mode"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"mode": param_name},
                }
                available_commands.append(
                    {
                        "id": "set_mode",
                        "label": "Set Mode",
                        "kind": "adjust",
                        "description": "Set the operating mode when supported by this ThinQ profile.",
                        "args_schema": {
                            "mode": {
                                "type": "string",
                                "label": "Mode",
                                "required": True,
                                "options": spec.get("options") or [],
                            }
                        },
                    }
                )

        if any(token in method_token for token in ("temp", "temperature")) and "set_target_temperature" not in command_map:
            numeric_param = _numeric_param(params, contains=("temp", "temperature")) or _numeric_param(params)
            if numeric_param is not None:
                param_name, spec = numeric_param
                command_map["set_target_temperature"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"temperature": param_name},
                }
                available_commands.append(
                    {
                        "id": "set_target_temperature",
                        "label": "Set Target Temperature",
                        "kind": "adjust",
                        "description": "Set a target temperature when supported by this ThinQ profile.",
                        "args_schema": {
                            "temperature": {
                                "type": "number",
                                "label": "Temperature",
                                "required": True,
                                "minimum": spec.get("minimum"),
                                "maximum": spec.get("maximum"),
                                "step": spec.get("step") or 1,
                                "unit": spec.get("unit") or "°C",
                            }
                        },
                    }
                )

        if any(token in method_token for token in ("fan", "wind", "speed")) and "set_fan_speed" not in command_map:
            option_param = _param_with_options(params, contains=("fan", "wind", "speed")) or _param_with_options(params)
            if option_param is not None:
                param_name, spec = option_param
                command_map["set_fan_speed"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"speed": param_name},
                }
                available_commands.append(
                    {
                        "id": "set_fan_speed",
                        "label": "Set Fan Speed",
                        "kind": "adjust",
                        "description": "Set fan or wind strength when supported by this ThinQ profile.",
                        "args_schema": {
                            "speed": {
                                "type": spec.get("type") or "string",
                                "label": "Speed",
                                "required": True,
                                "options": spec.get("options") or [],
                            }
                        },
                    }
                )

        if any(token in method_token for token in ("bright", "light")) and "set_brightness" not in command_map:
            numeric_param = _numeric_param(params, contains=("bright", "level")) or _numeric_param(params)
            if numeric_param is not None:
                param_name, spec = numeric_param
                command_map["set_brightness"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"brightness": param_name},
                }
                available_commands.append(
                    {
                        "id": "set_brightness",
                        "label": "Set Brightness",
                        "kind": "adjust",
                        "description": "Set brightness when supported by this ThinQ profile.",
                        "args_schema": {
                            "brightness": {
                                "type": "number",
                                "label": "Brightness",
                                "required": True,
                                "minimum": spec.get("minimum"),
                                "maximum": spec.get("maximum"),
                                "step": spec.get("step") or 1,
                                "unit": spec.get("unit") or "%",
                            }
                        },
                    }
                )

        if any(token in method_token for token in ("humidity", "humid")) and "set_target_humidity" not in command_map:
            numeric_param = _numeric_param(params, contains=("humid",)) or _numeric_param(params)
            if numeric_param is not None:
                param_name, spec = numeric_param
                command_map["set_target_humidity"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"humidity": param_name},
                }
                _append_command(
                    available_commands,
                    command_id="set_target_humidity",
                    label="Set Target Humidity",
                    kind="adjust",
                    description="Set a target humidity when supported by this ThinQ profile.",
                    args_schema={
                        "humidity": {
                            "type": "number",
                            "label": "Humidity",
                            "required": True,
                            "minimum": spec.get("minimum"),
                            "maximum": spec.get("maximum"),
                            "step": spec.get("step") or 1,
                            "unit": spec.get("unit") or "%",
                        }
                    },
                )

        if any(token in method_token for token in ("course", "cycle", "recipe")) and "set_course" not in command_map:
            option_param = _param_with_options(params, contains=("course", "cycle", "recipe")) or _param_with_options(params)
            if option_param is not None:
                param_name, spec = option_param
                command_map["set_course"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"course": param_name},
                }
                _append_command(
                    available_commands,
                    command_id="set_course",
                    label="Set Course",
                    kind="adjust",
                    description="Set an appliance course or cycle when supported by this ThinQ profile.",
                    args_schema={
                        "course": {
                            "type": "string",
                            "label": "Course",
                            "required": True,
                            "options": spec.get("options") or [],
                        }
                    },
                )

        if any(token in method_token for token in ("cook_mode", "cook")) and "set_cook_mode" not in command_map:
            option_param = _param_with_options(params, contains=("cook", "mode")) or _param_with_options(params)
            if option_param is not None:
                param_name, spec = option_param
                command_map["set_cook_mode"] = {
                    "control_method": method_id,
                    "control_params": {},
                    "arg_map": {"cook_mode": param_name},
                }
                _append_command(
                    available_commands,
                    command_id="set_cook_mode",
                    label="Set Cook Mode",
                    kind="adjust",
                    description="Set an oven cook mode when supported by this ThinQ profile.",
                    args_schema={
                        "cook_mode": {
                            "type": "string",
                            "label": "Cook Mode",
                            "required": True,
                            "options": spec.get("options") or [],
                        }
                    },
                )

    deduped_commands: list[dict[str, Any]] = []
    seen_command_ids: set[str] = set()
    for command in available_commands:
        command_id = command["id"]
        if command_id in seen_command_ids:
            continue
        seen_command_ids.add(command_id)
        deduped_commands.append(command)

    if "switch" not in capabilities:
        for command_id in ("turn_on", "turn_off", "toggle"):
            command_map.pop(command_id, None)
        deduped_commands = [command for command in deduped_commands if command["id"] not in {"toggle"}]

    documented = set(device_type_catalog(device_type).get("documented_commands") or documented_command_ids(capabilities))
    filtered_command_map = {
        command_id: payload
        for command_id, payload in command_map.items()
        if command_id in documented or command_id in {"refresh"}
    }
    deduped_commands = [
        command for command in deduped_commands
        if command["id"] in filtered_command_map or command["id"] == "refresh"
    ]

    return deduped_commands, filtered_command_map


def derive_capabilities(
    *,
    device_type: str,
    raw_status: dict[str, Any],
    available_controls: Any,
) -> list[str]:
    tokens = _collect_search_tokens(device_type, raw_status, available_controls)
    profile = device_type_catalog(device_type)
    profile_capabilities = set(profile.get("capabilities") or [])
    capabilities: set[str] = {"refresh", *profile_capabilities}

    if {"power", "operation", "on", "off", "switch"} & tokens:
        capabilities.add("switch")
    if {"temperature", "temp"} & tokens and not (
        profile.get("device_class") == "refrigeration"
        and "temperature" not in profile_capabilities
    ):
        capabilities.add("temperature")
    if {"target", "setpoint"} & tokens and "temperature" in tokens:
        capabilities.add("target_temperature")
    if "humidity" in tokens:
        capabilities.add("humidity")
    if "pm1" in tokens:
        capabilities.add("pm1")
    if "pm2" in tokens or "pm25" in tokens:
        capabilities.add("pm2")
    if "pm10" in tokens:
        capabilities.add("pm10")
    if "co2" in tokens:
        capabilities.add("co2")
    if "power" in tokens or "watt" in tokens:
        capabilities.add("power")
    if {"fan", "wind", "speed"} & tokens:
        capabilities.add("fan_speed")
    if "mode" in tokens:
        capabilities.add("mode")
    if {"brightness", "light"} & tokens:
        capabilities.add("brightness")
    if "door" in tokens:
        capabilities.add("door")
    if "battery" in tokens:
        capabilities.add("battery")
    if {"filter", "remain", "lifetime"} & tokens:
        capabilities.add("filter_life")

    return sorted(capabilities)


def derive_device_class(device_type: str, capabilities: list[str]) -> str:
    profile = device_type_catalog(device_type)
    if profile.get("device_class"):
        return str(profile["device_class"])
    token = slugify_token(device_type)
    if any(part in token for part in ("air_conditioner", "boiler", "thermostat")) or "target_temperature" in capabilities:
        return "climate"
    if any(part in token for part in ("air_purifier", "humidifier", "dehumidifier", "ventilator", "fan")):
        return "air-treatment"
    if any(part in token for part in ("washer", "dryer", "dish", "wash", "laundry")):
        return "laundry"
    if any(part in token for part in ("refrigerator", "freezer", "wine", "kimchi")):
        return "refrigeration"
    if any(part in token for part in ("oven", "cooktop", "hood", "microwave", "range")):
        return "kitchen"
    if any(part in token for part in ("vacuum", "robot")):
        return "vacuum"
    if "brightness" in capabilities:
        return "light"
    if "switch" in capabilities:
        return "switch"
    return token or "device"


def derive_entity_type(device_class: str, capabilities: list[str]) -> str:
    if "target_temperature" in capabilities:
        return "thermostat"
    if "brightness" in capabilities:
        return "light"
    if "switch" in capabilities and len(capabilities) <= 3:
        return "switch"
    if any(capability in capabilities for capability in ("temperature", "humidity", "co2", "pm2", "power")):
        return "sensor"
    if device_class in {"laundry", "refrigeration", "kitchen", "vacuum"}:
        return "appliance"
    return "device"


def derive_entity_type_for_device(device_type: str, device_class: str, capabilities: list[str]) -> str:
    profile = device_type_catalog(device_type)
    if profile.get("entity_type"):
        return str(profile["entity_type"])
    return derive_entity_type(device_class, capabilities)


def derive_dashboard(device_class: str, capabilities: list[str]) -> dict[str, Any]:
    if "target_temperature" in capabilities:
        return {
            "allowed_widgets": ["thermostat", "sensor-card", "stat", "line-chart", "external-widget"],
            "default_widget": "thermostat",
            "recommended_widgets": ["thermostat", "sensor-card"],
        }
    if "brightness" in capabilities:
        return {
            "allowed_widgets": ["light-card", "tile", "button", "stat", "external-widget"],
            "default_widget": "light-card",
            "recommended_widgets": ["light-card", "tile"],
        }
    if "switch" in capabilities:
        return {
            "allowed_widgets": ["tile", "button", "status-list", "stat", "external-widget"],
            "default_widget": "tile",
            "recommended_widgets": ["tile", "status-list"],
        }
    if device_class in {"laundry", "refrigeration", "kitchen", "vacuum"}:
        return {
            "allowed_widgets": ["external-widget", "status-list", "stat", "sensor-card"],
            "default_widget": "external-widget",
            "recommended_widgets": ["external-widget", "status-list"],
        }
    return {
        "allowed_widgets": ["sensor-card", "status-list", "stat", "line-chart", "gauge", "external-widget"],
        "default_widget": "sensor-card",
        "recommended_widgets": ["sensor-card", "status-list"],
    }


def normalize_device_snapshot(
    *,
    raw_device: dict[str, Any],
    raw_status: dict[str, Any] | None,
    raw_profile: dict[str, Any] | None,
    raw_available_controls: Any,
) -> dict[str, Any]:
    discovered = normalize_discovered_device(raw_device)
    status = raw_status or {}
    profile_catalog = device_type_catalog(discovered["device_type"])
    metrics, units = _extract_metrics(status)
    # Publish stable, end-user-oriented metric ids alongside the raw ThinQ
    # properties so one adaptive card can represent multiple appliance families.
    job_state = status.get("current_state") or status.get("run_state")
    if job_state is not None:
        metrics["appliance_state"] = job_state
    operating_mode = (
        status.get("mode")
        or status.get("current_mode")
        or status.get("washer_operation_mode")
    )
    if operating_mode is not None:
        metrics["mode"] = operating_mode
    door_state = status.get("door_state") or status.get("doorState")
    if door_state is not None:
        metrics["door"] = door_state
    primary_target_temperature = _primary_target_temperature(status)
    if primary_target_temperature is not None:
        target_temperature, target_temperature_unit = primary_target_temperature
        metrics["target_temperature"] = target_temperature
        units["target_temperature"] = target_temperature_unit
    elif "target_temperature_c" in metrics:
        metrics["target_temperature"] = metrics["target_temperature_c"]
        units["target_temperature"] = "°C"
    filter_value = next(
        (
            metrics[key]
            for key in (
                "filter_remain_percent",
                "fresh_air_filter_remain_percent",
                "water_filter_1_remain_percent",
            )
            if key in metrics
        ),
        None,
    )
    if filter_value is not None:
        metrics["filter_life"] = filter_value
        units["filter_life"] = "%"
    remain_hour = metrics.get("remain_hour")
    remain_minute = metrics.get("remain_minute")
    if isinstance(remain_hour, (int, float)) or isinstance(remain_minute, (int, float)):
        metrics["remaining_minutes"] = int(remain_hour or 0) * 60 + int(remain_minute or 0)
        units["remaining_minutes"] = "min"
    capabilities = derive_capabilities(
        device_type=discovered["device_type"],
        raw_status=status,
        available_controls=raw_available_controls,
    )
    if job_state is not None:
        capabilities.append("appliance_state")
    if "remaining_minutes" in metrics:
        capabilities.append("remaining_minutes")
    if "cycle_count" in metrics:
        capabilities.append("cycle_count")
    capabilities = sorted(set(capabilities))
    available_commands, command_map = build_command_catalog(
        device_type=discovered["device_type"],
        available_controls=raw_available_controls,
        capabilities=capabilities,
    )
    device_class = derive_device_class(discovered["device_type"], capabilities)
    entity_type = derive_entity_type_for_device(discovered["device_type"], device_class, capabilities)
    observed_resources, observed_properties = _observed_profile_terms(status, raw_profile or {})
    documented_capabilities = sorted(set(profile_catalog.get("capabilities") or capabilities))
    documented_resources = list(profile_catalog.get("resources") or [])
    documented_properties = list(profile_catalog.get("properties") or [])
    documented_commands_list = list(profile_catalog.get("documented_commands") or documented_command_ids(documented_capabilities))

    return {
        "device_id": discovered["device_id"],
        "device_name": discovered["device_name"],
        "device_type": discovered["device_type"],
        "model": discovered.get("model"),
        "model_id": discovered.get("model_id"),
        "platform_type": discovered.get("platform_type"),
        "online": bool(
            status.get("online")
            if isinstance(status.get("online"), bool)
            else status.get("connected", True)
        ),
        "device_class": device_class,
        "entity_type": entity_type,
        "capabilities": capabilities,
        "documented_capabilities": documented_capabilities,
        "available_commands": available_commands,
        "documented_commands": documented_commands_list,
        "command_map": command_map,
        "dashboard": derive_dashboard(device_class, capabilities),
        "metrics": metrics,
        "units": units,
        "device_profile": {
            "device_type": discovered["device_type"],
            "documented_resources": documented_resources,
            "documented_properties": documented_properties,
            "documented_capabilities": documented_capabilities,
            "documented_commands": documented_commands_list,
            "observed_resources": observed_resources,
            "observed_properties": observed_properties,
        },
        "summary": {
            "operation_state": status.get("operation_state") or status.get("operationState"),
            "job_state": status.get("current_state") or status.get("run_state"),
            "mode": status.get("mode") or status.get("current_mode"),
            "is_on": status.get("is_on")
            if isinstance(status.get("is_on"), bool)
            else status.get("power") == "ON" or status.get("operation") == "ON",
        },
        "raw": {
            "device": raw_device,
            "status": status,
            "profile": raw_profile or {},
            "available_controls": raw_available_controls or {},
        },
    }
