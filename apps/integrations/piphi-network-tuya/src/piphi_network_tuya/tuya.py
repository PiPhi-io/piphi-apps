from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .contract import (
    AIR_PURIFIER_ENTITY_CAPABILITIES,
    CLIMATE_ENTITY_CAPABILITIES,
    COVER_ENTITY_CAPABILITIES,
    FAN_ENTITY_CAPABILITIES,
    HUMIDIFIER_ENTITY_CAPABILITIES,
    LIGHT_ENTITY_CAPABILITIES,
    PLUG_ENTITY_CAPABILITIES,
    SWITCH_ENTITY_CAPABILITIES,
)
from .schemas import TuyaDeviceConfig
from .settings import tuya_discovery_timeout_seconds, tuya_io_timeout_seconds

try:
    import tinytuya
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    tinytuya = None


class TuyaClientError(RuntimeError):
    """Raised when a TinyTuya operation fails or returns an unusable response."""


DISCOVERY_PROFILE_COMMANDS: dict[str, list[str]] = {
    "plug": ["refresh", "turn_on", "turn_off", "set_dp"],
    "switch": ["refresh", "turn_on", "turn_off", "set_dp"],
    "light": [
        "refresh",
        "turn_on",
        "turn_off",
        "set_brightness",
        "set_color_temp",
        "set_color_rgb",
        "set_mode",
        "set_dp",
    ],
    "fan": [
        "refresh",
        "turn_on",
        "turn_off",
        "set_fan_speed",
        "set_oscillate",
        "set_mode",
        "set_dp",
    ],
    "cover": [
        "refresh",
        "open_cover",
        "close_cover",
        "stop_cover",
        "set_cover_position",
        "set_dp",
    ],
    "climate": [
        "refresh",
        "turn_on",
        "turn_off",
        "set_temperature",
        "set_mode",
        "set_dp",
    ],
    "humidifier": [
        "refresh",
        "turn_on",
        "turn_off",
        "set_humidity",
        "set_mode",
        "set_dp",
    ],
    "air_purifier": [
        "refresh",
        "turn_on",
        "turn_off",
        "set_fan_speed",
        "set_mode",
        "set_dp",
    ],
    "device": ["refresh", "turn_on", "turn_off", "set_dp"],
}

TUYA_CATEGORY_DEVICE_TYPES: dict[str, str] = {
    "cz": "plug",
    "pc": "plug",
    "kg": "switch",
    "dj": "light",
    "fs": "fan",
    "cl": "cover",
    "wk": "climate",
    "wkf": "climate",
    "jsq": "humidifier",
    "kj": "air_purifier",
}


@dataclass(slots=True)
class TuyaStatusSnapshot:
    metrics: dict[str, Any]
    units: dict[str, Any]
    raw: dict[str, Any]


@dataclass(slots=True)
class TuyaCommandResult:
    command: str
    raw: dict[str, Any]


def _require_tinytuya():
    if tinytuya is None:
        raise TuyaClientError(
            "tinytuya is not installed. Install project dependencies before using the Tuya runtime."
        )
    return tinytuya


def normalize_device_type(
    value: str | None,
    *,
    alias: str | None = None,
    product_name: str | None = None,
) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {
        "plug",
        "light",
        "switch",
        "fan",
        "cover",
        "climate",
        "humidifier",
        "air_purifier",
        "device",
    }:
        return candidate
    joined = " ".join(
        part for part in [candidate, alias or "", product_name or ""] if part
    ).lower()
    if any(token in joined for token in ("light", "bulb", "lamp", "strip")):
        return "light"
    if any(token in joined for token in ("fan", "ceiling fan", "blower")):
        return "fan"
    if any(
        token in joined for token in ("curtain", "blind", "shade", "cover", "shutter")
    ):
        return "cover"
    if any(
        token in joined
        for token in ("thermostat", "climate", "radiator", "heater", "heating")
    ):
        return "climate"
    if any(
        token in joined
        for token in ("humidifier", "dehumidifier", "diffuser", "aroma", "mist")
    ):
        return "humidifier"
    if any(token in joined for token in ("air purifier", "purifier", "hepa", "pm2.5")):
        return "air_purifier"
    if any(token in joined for token in ("plug", "outlet", "socket")):
        return "plug"
    if "switch" in joined:
        return "switch"
    return "plug" if not candidate else "device"


def _infer_device_type_from_dps(dps: Mapping[str, Any]) -> str | None:
    if not dps:
        return None
    dps_keys = {str(key) for key in dps.keys()}
    lowered_values = {
        str(value).strip().lower() for value in dps.values() if isinstance(value, str)
    }
    has_purifier_aqi_dp = any(
        _as_number(dps.get(key)) is not None
        and 0 <= float(_as_number(dps.get(key)) or 0) <= 500
        for key in ("22", "15")
    )
    has_purifier_mode_value = bool(
        lowered_values.intersection(
            {"auto", "sleep", "manual", "strong", "low", "medium", "high"}
        )
    )
    if has_purifier_aqi_dp and has_purifier_mode_value:
        return "air_purifier"
    has_light_dps = bool({"21", "23", "24", "25"}.intersection(dps_keys)) or {
        "20",
        "22",
    }.issubset(dps_keys)
    if has_light_dps:
        return "light"
    if lowered_values.intersection({"open", "close", "stop", "opening", "closing"}):
        return "cover"
    humidity_candidates = [
        _as_number(dps.get("103")),
        _as_number(dps.get("104")),
        _as_number(dps.get("13")),
        _as_number(dps.get("14")),
    ]
    humidity_numbers = [
        float(value)
        for value in humidity_candidates
        if value is not None and 0 <= float(value) <= 100
    ]
    has_humidifier_humidity_dps = bool(humidity_numbers)
    has_humidifier_mode_value = bool(
        lowered_values.intersection({"mist", "humidify", "dehumidify", "baby", "sleep"})
    )
    if has_humidifier_humidity_dps or has_humidifier_mode_value:
        return "humidifier"

    has_explicit_climate_temp_dps = bool(
        {"16", "24", "101", "102"}.intersection(dps_keys)
    )
    has_scaled_climate_temp_dps = any(
        _as_number(dps.get(key)) is not None
        and abs(float(_as_number(dps.get(key)) or 0)) > 100
        for key in ("103", "104")
    )
    has_simple_climate_temp_pair = {"2", "3"}.issubset(dps_keys)
    has_climate_mode_value = bool(
        lowered_values.intersection({"manual", "heat", "cool", "eco"})
    )
    if (
        has_explicit_climate_temp_dps
        or has_scaled_climate_temp_dps
        or has_simple_climate_temp_pair
        or has_climate_mode_value
    ) and any(_as_number(value) is not None for value in dps.values()):
        return "climate"
    if {"18", "19", "20", "4", "5", "6"}.intersection(dps_keys):
        return "plug"
    if len(_switch_dp_candidates(dps)) >= 1 and any(
        key in dps_keys for key in {"3", "4", "5"}
    ):
        non_boolean_controls = [
            value
            for key, value in dps.items()
            if str(key) in {"3", "4", "5"} and not isinstance(value, bool)
        ]
        if non_boolean_controls:
            return "fan"
    if len(_switch_dp_candidates(dps)) >= 1:
        return "switch"
    return None


def _infer_device_type_from_text(*values: str | None) -> str | None:
    joined = " ".join(str(value or "") for value in values).strip().lower()
    if not joined:
        return None
    if any(token in joined for token in ("light", "bulb", "lamp", "strip")):
        return "light"
    if any(token in joined for token in ("fan", "ceiling fan", "blower")):
        return "fan"
    if any(
        token in joined for token in ("curtain", "blind", "shade", "cover", "shutter")
    ):
        return "cover"
    if any(
        token in joined
        for token in ("thermostat", "climate", "radiator", "heater", "heating")
    ):
        return "climate"
    if any(
        token in joined
        for token in ("humidifier", "dehumidifier", "diffuser", "aroma", "mist")
    ):
        return "humidifier"
    if any(token in joined for token in ("air purifier", "purifier", "hepa", "pm2.5")):
        return "air_purifier"
    if any(token in joined for token in ("plug", "outlet", "socket", "receptacle")):
        return "plug"
    if "switch" in joined:
        return "switch"
    return None


def _map_tuya_category_device_type(category: str | None) -> str | None:
    token = str(category or "").strip().lower()
    if not token:
        return None
    compact = token.replace("_", "").replace("-", "")
    if compact in TUYA_CATEGORY_DEVICE_TYPES:
        return TUYA_CATEGORY_DEVICE_TYPES[compact]
    return _infer_device_type_from_text(token)


def _switch_dp_candidates(dps: Mapping[str, Any]) -> list[str]:
    keys = [
        str(key)
        for key, value in dps.items()
        if str(key).isdigit() and isinstance(value, bool)
    ]
    return sorted(set(keys), key=lambda value: int(value))


def _primary_power_dp(dps: Mapping[str, Any], device_type: str) -> str | None:
    switch_keys = _switch_dp_candidates(dps)
    if not switch_keys:
        return None
    if device_type == "light" and "20" in switch_keys:
        return "20"
    if "1" in switch_keys:
        return "1"
    return switch_keys[0]


def _light_feature_flags(dps: Mapping[str, Any]) -> dict[str, bool]:
    if not dps:
        return {
            "supports_mode": True,
            "supports_brightness": True,
            "supports_color_temp": True,
            "supports_rgb": True,
        }
    return {
        "supports_mode": any(key in dps for key in ("21", "2")),
        "supports_brightness": any(key in dps for key in ("22", "3")),
        "supports_color_temp": any(key in dps for key in ("23", "4")),
        "supports_rgb": any(key in dps for key in ("24", "5")),
    }


def _fan_speed_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("3", "4", "5"):
        value = dps.get(candidate)
        if value is not None and not isinstance(value, bool):
            if _as_number(value) is not None or isinstance(value, str):
                return candidate
    return None


def _fan_mode_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("4", "5", "6"):
        value = dps.get(candidate)
        if isinstance(value, str) and value.strip().lower() not in {
            "open",
            "close",
            "stop",
        }:
            return candidate
    return None


def _fan_oscillate_dp(
    dps: Mapping[str, Any], *, exclude: set[str] | None = None
) -> str | None:
    ignored = exclude or set()
    for candidate in ("5", "4", "6"):
        if candidate in ignored:
            continue
        value = dps.get(candidate)
        if isinstance(value, bool):
            return candidate
    return None


def _cover_control_dp(dps: Mapping[str, Any]) -> str | None:
    for key, value in dps.items():
        lowered = str(value).strip().lower() if isinstance(value, str) else ""
        if lowered in {"open", "close", "stop", "opening", "closing"}:
            return str(key)
    return "1" if "1" in dps else None


def _cover_position_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("2", "3", "5"):
        value = dps.get(candidate)
        if _as_number(value) is not None:
            return candidate
    return None


def _climate_target_temp_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("16", "2", "101", "103"):
        value = dps.get(candidate)
        if _as_number(value) is not None:
            return candidate
    return None


def _climate_current_temp_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("24", "3", "102", "104"):
        value = dps.get(candidate)
        if _as_number(value) is not None:
            return candidate
    return None


def _climate_mode_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("4", "5", "6", "2"):
        value = dps.get(candidate)
        if isinstance(value, str) and value.strip().lower() in {
            "auto",
            "manual",
            "heat",
            "cool",
            "eco",
            "off",
        }:
            return candidate
    return None


def _climate_temp_scale_from_value(value: Any) -> float:
    number = _as_number(value)
    if number is None:
        return 1.0
    return 10.0 if abs(float(number)) > 45 else 1.0


def _humidifier_target_humidity_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("103", "13", "3", "108"):
        value = dps.get(candidate)
        number = _as_number(value)
        if number is not None and 0 <= float(number) <= 100:
            return candidate
    return None


def _humidifier_current_humidity_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("104", "14", "4", "109"):
        value = dps.get(candidate)
        number = _as_number(value)
        if number is not None and 0 <= float(number) <= 100:
            return candidate
    return None


def _humidifier_mode_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("2", "5", "102"):
        value = dps.get(candidate)
        if isinstance(value, str) and value.strip():
            return candidate
    return None


def _humidifier_humidity_scale_from_value(value: Any) -> float:
    number = _as_number(value)
    if number is None:
        return 1.0
    return 10.0 if abs(float(number)) > 100 else 1.0


def _purifier_speed_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("4", "3", "5"):
        value = dps.get(candidate)
        if (
            value is not None
            and not isinstance(value, bool)
            and _as_number(value) is not None
        ):
            return candidate
    return None


def _purifier_mode_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("2", "3", "5", "102"):
        value = dps.get(candidate)
        if isinstance(value, str) and value.strip():
            return candidate
    return None


def _purifier_aqi_dp(dps: Mapping[str, Any]) -> str | None:
    for candidate in ("22", "101", "102", "15"):
        value = dps.get(candidate)
        number = _as_number(value)
        if number is not None and 0 <= float(number) <= 500:
            return candidate
    return None


def _purifier_aqi_scale_from_value(value: Any) -> float:
    number = _as_number(value)
    if number is None:
        return 1.0
    return 10.0 if abs(float(number)) > 500 else 1.0


def _profile_for_discovered_device(
    device_type: str, dps: Mapping[str, Any]
) -> dict[str, Any]:
    normalized = str(device_type or "device").lower()
    if normalized == "light":
        features = _light_feature_flags(dps)
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        commands = ["refresh", "turn_on", "turn_off", "set_dp"]
        if features["supports_mode"]:
            capabilities.append("mode")
            commands.append("set_mode")
        if features["supports_brightness"]:
            capabilities.append("brightness_percent")
            commands.append("set_brightness")
        if features["supports_color_temp"]:
            capabilities.append("color_temp_percent")
            commands.append("set_color_temp")
        if features["supports_rgb"]:
            capabilities.append("color_value")
            commands.append("set_color_rgb")
        ordered_capabilities = [
            name for name in LIGHT_ENTITY_CAPABILITIES if name in set(capabilities)
        ]
        ordered_commands = [
            name
            for name in DISCOVERY_PROFILE_COMMANDS["light"]
            if name in set(commands)
        ]
        return {
            "device_class": "light",
            "entity_type": "light",
            "supported_capabilities": ordered_capabilities,
            "supported_commands": ordered_commands,
            **features,
        }
    if normalized == "fan":
        speed_dp = _fan_speed_dp(dps)
        mode_dp = _fan_mode_dp(dps)
        oscillate_dp = _fan_oscillate_dp(dps, exclude={speed_dp} if speed_dp else None)
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        commands = ["refresh", "turn_on", "turn_off", "set_dp"]
        if speed_dp is not None:
            capabilities.append("fan_speed_percent")
            commands.append("set_fan_speed")
        if oscillate_dp is not None:
            capabilities.append("oscillating")
            commands.append("set_oscillate")
        if mode_dp is not None:
            capabilities.append("mode")
            commands.append("set_mode")
        return {
            "device_class": "fan",
            "entity_type": "fan",
            "supported_capabilities": [
                name for name in FAN_ENTITY_CAPABILITIES if name in set(capabilities)
            ],
            "supported_commands": [
                name
                for name in DISCOVERY_PROFILE_COMMANDS["fan"]
                if name in set(commands)
            ],
            "fan_speed_dp": speed_dp,
            "fan_mode_dp": mode_dp,
            "fan_oscillate_dp": oscillate_dp,
        }
    if normalized == "cover":
        control_dp = _cover_control_dp(dps)
        position_dp = _cover_position_dp(dps)
        capabilities = [
            "connected",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "set_dp",
        ]
        commands = ["refresh", "set_dp"]
        if control_dp is not None:
            capabilities.append("motion_state")
            commands.extend(["open_cover", "close_cover", "stop_cover"])
        if position_dp is not None:
            capabilities.append("position_percent")
            commands.append("set_cover_position")
        return {
            "device_class": "cover",
            "entity_type": "cover",
            "supported_capabilities": [
                name for name in COVER_ENTITY_CAPABILITIES if name in set(capabilities)
            ],
            "supported_commands": [
                name
                for name in DISCOVERY_PROFILE_COMMANDS["cover"]
                if name in set(commands)
            ],
            "cover_control_dp": control_dp,
            "cover_position_dp": position_dp,
        }
    if normalized == "climate":
        target_temp_dp = _climate_target_temp_dp(dps)
        current_temp_dp = _climate_current_temp_dp(dps)
        mode_dp = _climate_mode_dp(dps)
        scale_source = None
        if target_temp_dp is not None:
            scale_source = dps.get(target_temp_dp)
        elif current_temp_dp is not None:
            scale_source = dps.get(current_temp_dp)
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        commands = ["refresh", "turn_on", "turn_off", "set_dp"]
        if current_temp_dp is not None:
            capabilities.append("temperature_c")
        if target_temp_dp is not None:
            capabilities.append("target_temperature_c")
            commands.append("set_temperature")
        if mode_dp is not None:
            capabilities.append("mode")
            commands.append("set_mode")
        return {
            "device_class": "climate",
            "entity_type": "climate",
            "supported_capabilities": [
                name
                for name in CLIMATE_ENTITY_CAPABILITIES
                if name in set(capabilities)
            ],
            "supported_commands": [
                name
                for name in DISCOVERY_PROFILE_COMMANDS["climate"]
                if name in set(commands)
            ],
            "climate_target_temp_dp": target_temp_dp,
            "climate_current_temp_dp": current_temp_dp,
            "climate_mode_dp": mode_dp,
            "climate_temp_scale": _climate_temp_scale_from_value(scale_source),
        }
    if normalized == "humidifier":
        target_humidity_dp = _humidifier_target_humidity_dp(dps)
        current_humidity_dp = _humidifier_current_humidity_dp(dps)
        mode_dp = _humidifier_mode_dp(dps)
        scale_source = None
        if target_humidity_dp is not None:
            scale_source = dps.get(target_humidity_dp)
        elif current_humidity_dp is not None:
            scale_source = dps.get(current_humidity_dp)
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        commands = ["refresh", "turn_on", "turn_off", "set_dp"]
        if current_humidity_dp is not None:
            capabilities.append("humidity_percent")
        if target_humidity_dp is not None:
            capabilities.append("target_humidity_percent")
            commands.append("set_humidity")
        if mode_dp is not None:
            capabilities.append("mode")
            commands.append("set_mode")
        return {
            "device_class": "humidifier",
            "entity_type": "humidifier",
            "supported_capabilities": [
                name
                for name in HUMIDIFIER_ENTITY_CAPABILITIES
                if name in set(capabilities)
            ],
            "supported_commands": [
                name
                for name in DISCOVERY_PROFILE_COMMANDS["humidifier"]
                if name in set(commands)
            ],
            "humidifier_target_humidity_dp": target_humidity_dp,
            "humidifier_current_humidity_dp": current_humidity_dp,
            "humidifier_mode_dp": mode_dp,
            "humidifier_humidity_scale": _humidifier_humidity_scale_from_value(
                scale_source
            ),
        }
    if normalized == "air_purifier":
        speed_dp = _purifier_speed_dp(dps)
        mode_dp = _purifier_mode_dp(dps)
        aqi_dp = _purifier_aqi_dp(dps)
        aqi_source = dps.get(aqi_dp) if aqi_dp is not None else None
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        commands = ["refresh", "turn_on", "turn_off", "set_dp"]
        if speed_dp is not None:
            capabilities.append("fan_speed_percent")
            commands.append("set_fan_speed")
        if mode_dp is not None:
            capabilities.append("mode")
            commands.append("set_mode")
        if aqi_dp is not None:
            capabilities.append("air_quality_index")
        return {
            "device_class": "air_purifier",
            "entity_type": "air_purifier",
            "supported_capabilities": [
                name
                for name in AIR_PURIFIER_ENTITY_CAPABILITIES
                if name in set(capabilities)
            ],
            "supported_commands": [
                name
                for name in DISCOVERY_PROFILE_COMMANDS["air_purifier"]
                if name in set(commands)
            ],
            "purifier_speed_dp": speed_dp,
            "purifier_speed_max": _discrete_scale_for_speed(dps.get(speed_dp))
            if speed_dp is not None
            else 3,
            "purifier_mode_dp": mode_dp,
            "purifier_aqi_dp": aqi_dp,
            "purifier_aqi_scale": _purifier_aqi_scale_from_value(aqi_source),
        }
    if normalized == "plug":
        supports_energy = any(key in dps for key in ("18", "19", "20", "4", "5", "6"))
        capabilities = [
            "connected",
            "power",
            "latency_ms",
            "dp_count",
            "protocol_version",
            "refresh",
            "turn_on",
            "turn_off",
            "set_dp",
        ]
        if supports_energy:
            capabilities.extend(["current_ma", "power_w", "voltage_v"])
        return {
            "device_class": "outlet",
            "entity_type": "switch",
            "supported_capabilities": [
                name for name in PLUG_ENTITY_CAPABILITIES if name in set(capabilities)
            ],
            "supported_commands": DISCOVERY_PROFILE_COMMANDS["plug"],
            "supports_energy_monitoring": supports_energy,
        }
    if normalized == "switch":
        supports_energy = any(key in dps for key in ("18", "19", "20", "4", "5", "6"))
        return {
            "device_class": "switch",
            "entity_type": "switch",
            "supported_capabilities": SWITCH_ENTITY_CAPABILITIES,
            "supported_commands": DISCOVERY_PROFILE_COMMANDS["switch"],
            "supports_energy_monitoring": supports_energy,
        }
    return {
        "device_class": "device",
        "entity_type": "device",
        "supported_capabilities": SWITCH_ENTITY_CAPABILITIES,
        "supported_commands": DISCOVERY_PROFILE_COMMANDS["device"],
    }


def _resolve_discovered_device_type(
    *,
    category: str | None,
    alias: str | None,
    product_name: str | None,
    dps: Mapping[str, Any],
) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []
    category_type = _map_tuya_category_device_type(category)
    if category_type is not None:
        candidates.append((100, category_type, "tuya_category"))
    dps_type = _infer_device_type_from_dps(dps)
    dps_weights = {
        "light": 90,
        "climate": 86,
        "humidifier": 85,
        "air_purifier": 84,
        "cover": 83,
        "fan": 82,
        "plug": 70,
        "switch": 40,
    }
    if dps_type in dps_weights:
        candidates.append((dps_weights[dps_type], dps_type, "dps"))
    text_type = _infer_device_type_from_text(alias, product_name)
    if text_type is not None:
        candidates.append((80, text_type, "product_name"))
    fallback_type = normalize_device_type(
        category or "", alias=alias, product_name=product_name
    )
    candidates.append((10, fallback_type, "fallback"))
    _, device_type, source = max(candidates, key=lambda item: item[0])
    return device_type, source


def _build_discovery_hints(
    *,
    dps: Mapping[str, Any],
    alias: str,
    product_name: str,
    category: str | None,
    device_type: str,
    device_class: str,
    entity_type: str,
    classification_source: str,
    supported_capabilities: list[str],
    supported_commands: list[str],
) -> dict[str, Any]:
    lowered_text = f"{alias} {product_name}".lower()
    switch_candidates = _switch_dp_candidates(dps)
    primary_power = _primary_power_dp(dps, device_type)
    profile = _profile_for_discovered_device(device_type, dps)
    hints: dict[str, Any] = {
        "suspected_device_type": device_type,
        "classification_source": classification_source,
        "expected_device_class": device_class,
        "expected_entity_type": entity_type,
        "dps_keys": sorted(str(key) for key in dps.keys()),
        "switch_dp_candidates": switch_candidates,
        "switch_channel_count": len(switch_candidates),
        "supported_capabilities": supported_capabilities,
        "supported_commands": supported_commands,
    }
    if category:
        hints["tuya_category"] = category
    if primary_power is not None:
        hints["primary_power_dp"] = primary_power
    if device_type == "light":
        hints["supports_mode"] = bool(profile.get("supports_mode"))
        hints["supports_brightness"] = bool(profile.get("supports_brightness"))
        hints["supports_color_temp"] = bool(profile.get("supports_color_temp"))
        hints["supports_rgb"] = bool(profile.get("supports_rgb"))
    if device_type == "fan":
        hints["fan_speed_dp"] = profile.get("fan_speed_dp")
        hints["fan_mode_dp"] = profile.get("fan_mode_dp")
        hints["fan_oscillate_dp"] = profile.get("fan_oscillate_dp")
    if device_type == "cover":
        hints["cover_control_dp"] = profile.get("cover_control_dp")
        hints["cover_position_dp"] = profile.get("cover_position_dp")
    if device_type == "climate":
        hints["climate_target_temp_dp"] = profile.get("climate_target_temp_dp")
        hints["climate_current_temp_dp"] = profile.get("climate_current_temp_dp")
        hints["climate_mode_dp"] = profile.get("climate_mode_dp")
        hints["climate_temp_scale"] = profile.get("climate_temp_scale")
    if device_type == "humidifier":
        hints["humidifier_target_humidity_dp"] = profile.get(
            "humidifier_target_humidity_dp"
        )
        hints["humidifier_current_humidity_dp"] = profile.get(
            "humidifier_current_humidity_dp"
        )
        hints["humidifier_mode_dp"] = profile.get("humidifier_mode_dp")
        hints["humidifier_humidity_scale"] = profile.get("humidifier_humidity_scale")
    if device_type == "air_purifier":
        hints["purifier_speed_dp"] = profile.get("purifier_speed_dp")
        hints["purifier_speed_max"] = profile.get("purifier_speed_max")
        hints["purifier_mode_dp"] = profile.get("purifier_mode_dp")
        hints["purifier_aqi_dp"] = profile.get("purifier_aqi_dp")
        hints["purifier_aqi_scale"] = profile.get("purifier_aqi_scale")
    if device_type in {"plug", "switch"}:
        hints["supports_energy_monitoring"] = bool(
            profile.get("supports_energy_monitoring")
        )
        hints["supports_multi_switch"] = len(switch_candidates) > 1
    if "strip" in lowered_text:
        hints["form_factor"] = "light_strip"
    elif "bulb" in lowered_text or "lamp" in lowered_text:
        hints["form_factor"] = "bulb"
    elif "plug" in lowered_text or "outlet" in lowered_text or "socket" in lowered_text:
        hints["form_factor"] = "plug"
    elif "fan" in lowered_text:
        hints["form_factor"] = "fan"
    elif any(
        token in lowered_text
        for token in ("curtain", "blind", "shade", "cover", "shutter")
    ):
        hints["form_factor"] = "cover"
    elif any(
        token in lowered_text
        for token in ("humidifier", "dehumidifier", "diffuser", "aroma", "mist")
    ):
        hints["form_factor"] = "humidifier"
    elif any(
        token in lowered_text for token in ("air purifier", "purifier", "hepa", "pm2.5")
    ):
        hints["form_factor"] = "air_purifier"
    elif "switch" in lowered_text:
        hints["form_factor"] = "switch"
    return hints


def _build_discovery_record(
    *,
    tuya_device_id: str,
    host: str,
    alias: str,
    version: Any = None,
    category: str | None = None,
    product_id: Any = None,
    product_name: str | None = None,
    discovery_source: str,
    dps: Mapping[str, Any] | None = None,
    discovery_error: str | None = None,
) -> dict[str, Any]:
    normalized_dps = {str(key): value for key, value in (dps or {}).items()}
    resolved_device_type, classification_source = _resolve_discovered_device_type(
        category=category,
        alias=alias,
        product_name=product_name,
        dps=normalized_dps,
    )
    profile = _profile_for_discovered_device(resolved_device_type, normalized_dps)
    primary_power = _primary_power_dp(normalized_dps, resolved_device_type)
    suggested_config: dict[str, Any] = {
        "device_type": resolved_device_type,
        "switch": int(primary_power)
        if primary_power and primary_power.isdigit()
        else 1,
    }
    if resolved_device_type == "fan":
        if profile.get("fan_speed_dp"):
            suggested_config["fan_speed_dp"] = int(str(profile["fan_speed_dp"]))
            speed_value = normalized_dps.get(str(profile["fan_speed_dp"]))
            suggested_config["fan_speed_max"] = _discrete_scale_for_speed(speed_value)
        if profile.get("fan_mode_dp"):
            suggested_config["fan_mode_dp"] = int(str(profile["fan_mode_dp"]))
        if profile.get("fan_oscillate_dp"):
            suggested_config["fan_oscillate_dp"] = int(str(profile["fan_oscillate_dp"]))
    if resolved_device_type == "cover":
        if profile.get("cover_control_dp"):
            suggested_config["cover_control_dp"] = int(str(profile["cover_control_dp"]))
        if profile.get("cover_position_dp"):
            suggested_config["cover_position_dp"] = int(
                str(profile["cover_position_dp"])
            )
    if resolved_device_type == "climate":
        if profile.get("climate_target_temp_dp"):
            suggested_config["climate_target_temp_dp"] = int(
                str(profile["climate_target_temp_dp"])
            )
        if profile.get("climate_current_temp_dp"):
            suggested_config["climate_current_temp_dp"] = int(
                str(profile["climate_current_temp_dp"])
            )
        if profile.get("climate_mode_dp"):
            suggested_config["climate_mode_dp"] = int(str(profile["climate_mode_dp"]))
        if profile.get("climate_temp_scale"):
            suggested_config["climate_temp_scale"] = float(
                profile["climate_temp_scale"]
            )
    if resolved_device_type == "humidifier":
        if profile.get("humidifier_target_humidity_dp"):
            suggested_config["humidifier_target_humidity_dp"] = int(
                str(profile["humidifier_target_humidity_dp"])
            )
        if profile.get("humidifier_current_humidity_dp"):
            suggested_config["humidifier_current_humidity_dp"] = int(
                str(profile["humidifier_current_humidity_dp"])
            )
        if profile.get("humidifier_mode_dp"):
            suggested_config["humidifier_mode_dp"] = int(
                str(profile["humidifier_mode_dp"])
            )
        if profile.get("humidifier_humidity_scale"):
            suggested_config["humidifier_humidity_scale"] = float(
                profile["humidifier_humidity_scale"]
            )
    if resolved_device_type == "air_purifier":
        if profile.get("purifier_speed_dp"):
            suggested_config["purifier_speed_dp"] = int(
                str(profile["purifier_speed_dp"])
            )
        if profile.get("purifier_speed_max"):
            suggested_config["purifier_speed_max"] = int(
                str(profile["purifier_speed_max"])
            )
        if profile.get("purifier_mode_dp"):
            suggested_config["purifier_mode_dp"] = int(str(profile["purifier_mode_dp"]))
        if profile.get("purifier_aqi_dp"):
            suggested_config["purifier_aqi_dp"] = int(str(profile["purifier_aqi_dp"]))
        if profile.get("purifier_aqi_scale"):
            suggested_config["purifier_aqi_scale"] = float(
                profile["purifier_aqi_scale"]
            )
    resolved_config_preview: dict[str, Any] = {
        "host": host,
        "tuya_device_id": tuya_device_id,
        "alias": alias,
        "device_type": resolved_device_type,
        "switch": suggested_config["switch"],
        "version": "3.3",
        "poll_interval_seconds": 60,
    }
    if resolved_device_type in {
        "fan",
        "cover",
        "climate",
        "humidifier",
        "air_purifier",
    }:
        for key, value in suggested_config.items():
            if key not in {"device_type", "switch"}:
                resolved_config_preview[key] = value
    record: dict[str, Any] = {
        "id": tuya_device_id,
        "device_id": tuya_device_id,
        "tuya_device_id": tuya_device_id,
        "host": host,
        "alias": alias,
        "device_type": resolved_device_type,
        "device_class": profile["device_class"],
        "entity_type": profile["entity_type"],
        "supported_capabilities": profile["supported_capabilities"],
        "supported_commands": profile["supported_commands"],
        "tuya_category": category or None,
        "product_id": product_id,
        "product_name": product_name or None,
        "discovery_source": discovery_source,
        "discovery_hints": _build_discovery_hints(
            dps=normalized_dps,
            alias=alias,
            product_name=product_name or "",
            category=category,
            device_type=resolved_device_type,
            device_class=profile["device_class"],
            entity_type=profile["entity_type"],
            classification_source=classification_source,
            supported_capabilities=profile["supported_capabilities"],
            supported_commands=profile["supported_commands"],
        ),
        "suggested_config": suggested_config,
        "resolved_config_preview": resolved_config_preview,
        "missing_required_fields": ["local_key"],
    }
    if version is not None:
        record["version"] = str(version)
        record["suggested_config"]["version"] = str(version)
        record["resolved_config_preview"]["version"] = str(version)
    if normalized_dps:
        record["dps_preview"] = normalized_dps
    if discovery_error:
        record["discovery_error"] = discovery_error
    return record


def _coerce_version(value: str) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def close_device(device: Any) -> None:
    for method_name in ("close", "disconnect"):
        method = getattr(device, method_name, None)
        if callable(method):
            try:
                method()
            except Exception:
                return
            return


def _instantiate_device(config: TuyaDeviceConfig, *, persist: bool = False) -> Any:
    module = _require_tinytuya()
    device_type = normalize_device_type(config.device_type, alias=config.alias)
    class_name = {
        "plug": "OutletDevice",
        "switch": "OutletDevice",
        "light": "BulbDevice",
        "fan": "Device",
        "cover": "Device",
        "climate": "Device",
        "humidifier": "Device",
        "air_purifier": "Device",
        "device": "Device",
    }.get(device_type, "Device")
    device_cls = getattr(module, class_name, None) or getattr(module, "Device", None)
    if device_cls is None:
        raise TuyaClientError("Unable to resolve a TinyTuya device class.")

    constructor_kwargs = {
        "dev_id": config.tuya_device_id,
        "address": config.host,
        "local_key": config.local_key,
        "persist": persist,
    }
    try:
        device = device_cls(
            config.tuya_device_id, config.host, config.local_key, persist=persist
        )
    except TypeError:
        try:
            device = device_cls(**constructor_kwargs)
        except TypeError as exc:
            raise TuyaClientError(
                f"Unable to initialize TinyTuya device: {exc}"
            ) from exc

    set_version = getattr(device, "set_version", None)
    if callable(set_version):
        set_version(_coerce_version(config.version))
    set_persistent = getattr(device, "set_socketPersistent", None)
    if callable(set_persistent):
        set_persistent(persist)
    return device


def open_persistent_device(config: TuyaDeviceConfig) -> Any:
    return _instantiate_device(config, persist=True)


def _normalize_raw_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {"result": raw}


def _extract_dps(raw: Mapping[str, Any]) -> dict[str, Any]:
    dps = raw.get("dps")
    if isinstance(dps, dict):
        return dps
    result = raw.get("result")
    if isinstance(result, dict) and isinstance(result.get("dps"), dict):
        return result["dps"]
    return {}


def _extract_power_state(
    dps: Mapping[str, Any], switch: int, device_type: str
) -> bool | None:
    candidates: list[str] = [str(switch), "1"]
    if device_type == "light":
        candidates = ["20", str(switch), "1"]
    elif device_type in {"fan", "air_purifier"}:
        candidates = [str(switch), "1"]
    for candidate in candidates:
        if candidate in dps and isinstance(dps[candidate], bool):
            return dps[candidate]
    return None


def _unit_for_value(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "count"
    if isinstance(value, float):
        return "number"
    if value is None:
        return "unknown"
    return "string"


def _jsonish_value(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        lowered = stripped.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def _as_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _get_dps_value(dps: Mapping[str, Any], *keys: int | str) -> Any:
    for key in keys:
        lookup = str(key)
        if lookup in dps:
            return dps[lookup]
    return None


def _normalized_percent(value: Any, *, low: float, high: float) -> float | None:
    number = _as_number(value)
    if number is None:
        return None
    if 0 <= number <= 100:
        return round(float(number), 2)
    clamped = min(max(float(number), low), high)
    if high <= low:
        return None
    return round(((clamped - low) / (high - low)) * 100, 2)


def _discrete_scale_for_speed(value: Any) -> int:
    number = _as_number(value)
    if number is None:
        return 3
    if number <= 3:
        return 3
    if number <= 5:
        return 5
    if number <= 10:
        return 10
    return 100


def _fan_speed_percent(value: Any, *, configured_max: int) -> float | None:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"low", "min"}:
            return 33.0
        if lowered in {"medium", "mid"}:
            return 67.0
        if lowered in {"high", "max"}:
            return 100.0
    number = _as_number(value)
    if number is None:
        return None
    max_value = max(configured_max, _discrete_scale_for_speed(number))
    return round(
        min(max(float(number), 0.0), float(max_value)) / float(max_value) * 100, 2
    )


def _add_numeric_metric(
    metrics: dict[str, Any],
    units: dict[str, Any],
    *,
    name: str,
    value: Any,
    unit: str,
    scale: float = 1.0,
) -> None:
    number = _as_number(value)
    if number is None:
        return
    metric_value = round(float(number) / scale, 3) if scale != 1.0 else number
    metrics[name] = metric_value
    units[name] = unit


def _enrich_plug_metrics(
    dps: Mapping[str, Any], metrics: dict[str, Any], units: dict[str, Any]
) -> None:
    _add_numeric_metric(
        metrics, units, name="current_ma", value=_get_dps_value(dps, 18, 4), unit="mA"
    )
    _add_numeric_metric(
        metrics,
        units,
        name="power_w",
        value=_get_dps_value(dps, 19, 5),
        unit="W",
        scale=10.0,
    )
    _add_numeric_metric(
        metrics,
        units,
        name="voltage_v",
        value=_get_dps_value(dps, 20, 6),
        unit="V",
        scale=10.0,
    )


def _enrich_light_metrics(
    dps: Mapping[str, Any], metrics: dict[str, Any], units: dict[str, Any]
) -> None:
    mode = _get_dps_value(dps, 21, 2)
    if mode is not None:
        metrics["mode"] = mode
        units["mode"] = "string"

    brightness = _normalized_percent(_get_dps_value(dps, 22, 3), low=10.0, high=1000.0)
    if brightness is None:
        brightness = _normalized_percent(
            _get_dps_value(dps, 22, 3), low=25.0, high=255.0
        )
    if brightness is not None:
        metrics["brightness_percent"] = brightness
        units["brightness_percent"] = "%"

    color_temp = _normalized_percent(_get_dps_value(dps, 23, 4), low=0.0, high=1000.0)
    if color_temp is None:
        color_temp = _normalized_percent(
            _get_dps_value(dps, 23, 4), low=0.0, high=255.0
        )
    if color_temp is not None:
        metrics["color_temp_percent"] = color_temp
        units["color_temp_percent"] = "%"

    color_value = _get_dps_value(dps, 24, 5)
    if color_value is not None:
        metrics["color_value"] = color_value
        units["color_value"] = "string"


def _enrich_fan_metrics(
    config: TuyaDeviceConfig,
    dps: Mapping[str, Any],
    metrics: dict[str, Any],
    units: dict[str, Any],
) -> None:
    speed_value = _get_dps_value(dps, config.fan_speed_dp, 3, 4, 5)
    speed_percent = _fan_speed_percent(
        speed_value, configured_max=max(1, int(config.fan_speed_max))
    )
    if speed_percent is not None:
        metrics["fan_speed_percent"] = speed_percent
        units["fan_speed_percent"] = "%"

    oscillate_candidates: list[int | str] = []
    if config.fan_oscillate_dp is not None:
        oscillate_candidates.append(config.fan_oscillate_dp)
    oscillate_candidates.extend([5, 4, 6])
    oscillating = _get_dps_value(dps, *oscillate_candidates)
    if isinstance(oscillating, bool):
        metrics["oscillating"] = oscillating
        units["oscillating"] = "bool"

    mode_candidates: list[int | str] = []
    if config.fan_mode_dp is not None:
        mode_candidates.append(config.fan_mode_dp)
    mode_candidates.extend([4, 5, 6])
    mode = _get_dps_value(dps, *mode_candidates)
    if isinstance(mode, str) and mode.strip().lower() not in {"open", "close", "stop"}:
        metrics["mode"] = mode
        units["mode"] = "string"


def _temperature_metric(value: Any, *, scale: float) -> float | None:
    number = _as_number(value)
    if number is None:
        return None
    return round(float(number) / max(scale, 0.001), 2)


def _enrich_cover_metrics(
    config: TuyaDeviceConfig,
    dps: Mapping[str, Any],
    metrics: dict[str, Any],
    units: dict[str, Any],
) -> None:
    control_candidates: list[int | str] = [config.cover_control_dp, 1]
    motion_value = _get_dps_value(dps, *control_candidates)
    if isinstance(motion_value, str):
        lowered = motion_value.strip().lower()
        state_map = {
            "open": "opening",
            "opening": "opening",
            "close": "closing",
            "closing": "closing",
            "stop": "stopped",
            "pause": "stopped",
        }
        metrics["motion_state"] = state_map.get(lowered, lowered)
        units["motion_state"] = "string"

    position_candidates: list[int | str] = []
    if config.cover_position_dp is not None:
        position_candidates.append(config.cover_position_dp)
    position_candidates.extend([2, 3, 5])
    position_percent = _normalized_percent(
        _get_dps_value(dps, *position_candidates), low=0.0, high=1000.0
    )
    if position_percent is None:
        position_percent = _normalized_percent(
            _get_dps_value(dps, *position_candidates), low=0.0, high=100.0
        )
    if position_percent is not None:
        metrics["position_percent"] = position_percent
        units["position_percent"] = "%"


def _enrich_climate_metrics(
    config: TuyaDeviceConfig,
    dps: Mapping[str, Any],
    metrics: dict[str, Any],
    units: dict[str, Any],
) -> None:
    target_candidates: list[int | str] = [
        config.climate_target_temp_dp,
        16,
        2,
        101,
        103,
    ]
    target_raw = _get_dps_value(dps, *target_candidates)
    scale = float(config.climate_temp_scale or 1.0)
    if scale == 1.0 and target_raw is not None:
        scale = _climate_temp_scale_from_value(target_raw)
    current_candidates: list[int | str] = []
    if config.climate_current_temp_dp is not None:
        current_candidates.append(config.climate_current_temp_dp)
    current_candidates.extend([24, 3, 102, 104])
    current_raw = _get_dps_value(dps, *current_candidates)
    if current_raw is not None and float(config.climate_temp_scale or 1.0) == 1.0:
        scale = max(scale, _climate_temp_scale_from_value(current_raw))

    target_temp = _temperature_metric(target_raw, scale=scale)
    if target_temp is not None:
        metrics["target_temperature_c"] = target_temp
        units["target_temperature_c"] = "C"

    current_temp = _temperature_metric(current_raw, scale=scale)
    if current_temp is not None:
        metrics["temperature_c"] = current_temp
        units["temperature_c"] = "C"

    mode_candidates: list[int | str] = []
    if config.climate_mode_dp is not None:
        mode_candidates.append(config.climate_mode_dp)
    mode_candidates.extend([4, 5, 6, 2])
    mode = _get_dps_value(dps, *mode_candidates)
    if isinstance(mode, str):
        metrics["mode"] = mode
        units["mode"] = "string"


def _enrich_humidifier_metrics(
    config: TuyaDeviceConfig,
    dps: Mapping[str, Any],
    metrics: dict[str, Any],
    units: dict[str, Any],
) -> None:
    target_candidates: list[int | str] = [
        config.humidifier_target_humidity_dp,
        103,
        13,
        3,
        108,
    ]
    target_raw = _get_dps_value(dps, *target_candidates)
    scale = float(config.humidifier_humidity_scale or 1.0)
    if scale == 1.0 and target_raw is not None:
        scale = _humidifier_humidity_scale_from_value(target_raw)

    current_candidates: list[int | str] = []
    if config.humidifier_current_humidity_dp is not None:
        current_candidates.append(config.humidifier_current_humidity_dp)
    current_candidates.extend([104, 14, 4, 109])
    current_raw = _get_dps_value(dps, *current_candidates)
    if (
        current_raw is not None
        and float(config.humidifier_humidity_scale or 1.0) == 1.0
    ):
        scale = max(scale, _humidifier_humidity_scale_from_value(current_raw))

    target_humidity = _temperature_metric(target_raw, scale=scale)
    if target_humidity is not None:
        metrics["target_humidity_percent"] = target_humidity
        units["target_humidity_percent"] = "%"

    current_humidity = _temperature_metric(current_raw, scale=scale)
    if current_humidity is not None:
        metrics["humidity_percent"] = current_humidity
        units["humidity_percent"] = "%"

    mode_candidates: list[int | str] = []
    if config.humidifier_mode_dp is not None:
        mode_candidates.append(config.humidifier_mode_dp)
    mode_candidates.extend([2, 5, 102])
    mode = _get_dps_value(dps, *mode_candidates)
    if isinstance(mode, str):
        metrics["mode"] = mode
        units["mode"] = "string"


def _enrich_air_purifier_metrics(
    config: TuyaDeviceConfig,
    dps: Mapping[str, Any],
    metrics: dict[str, Any],
    units: dict[str, Any],
) -> None:
    speed_value = _get_dps_value(dps, config.purifier_speed_dp, 4, 3, 5)
    speed_percent = _fan_speed_percent(
        speed_value, configured_max=max(1, int(config.purifier_speed_max))
    )
    if speed_percent is not None:
        metrics["fan_speed_percent"] = speed_percent
        units["fan_speed_percent"] = "%"

    mode_candidates: list[int | str] = []
    if config.purifier_mode_dp is not None:
        mode_candidates.append(config.purifier_mode_dp)
    mode_candidates.extend([2, 3, 5, 102])
    mode = _get_dps_value(dps, *mode_candidates)
    if isinstance(mode, str):
        metrics["mode"] = mode
        units["mode"] = "string"

    aqi_candidates: list[int | str] = []
    if config.purifier_aqi_dp is not None:
        aqi_candidates.append(config.purifier_aqi_dp)
    aqi_candidates.extend([22, 101, 102, 15])
    aqi_raw = _get_dps_value(dps, *aqi_candidates)
    aqi_scale = float(config.purifier_aqi_scale or 1.0)
    if aqi_scale == 1.0 and aqi_raw is not None:
        aqi_scale = _purifier_aqi_scale_from_value(aqi_raw)
    _add_numeric_metric(
        metrics,
        units,
        name="air_quality_index",
        value=aqi_raw,
        unit="AQI",
        scale=aqi_scale,
    )


def _status_sync(device: Any) -> dict[str, Any]:
    status_method = getattr(device, "status", None)
    if not callable(status_method):
        raise TuyaClientError(
            "TinyTuya device does not expose a callable status() method."
        )
    return _normalize_raw_payload(status_method())


def _power_sync(device: Any, *, enabled: bool, switch: int) -> dict[str, Any]:
    method_name = "turn_on" if enabled else "turn_off"
    method = getattr(device, method_name, None)
    if callable(method):
        return _normalize_raw_payload(method(switch=switch))
    set_status = getattr(device, "set_status", None)
    if callable(set_status):
        return _normalize_raw_payload(set_status(enabled, switch=switch))
    raise TuyaClientError(
        "TinyTuya device does not expose turn_on/turn_off or set_status()."
    )


def _set_dp_sync(device: Any, dp: str, value: Any) -> dict[str, Any]:
    if hasattr(device, "set_value") and callable(device.set_value):
        return _normalize_raw_payload(device.set_value(dp, value))
    if hasattr(device, "set_status") and callable(device.set_status):
        return _normalize_raw_payload(device.set_status(value, switch=int(dp)))
    raise TuyaClientError(
        "TinyTuya device does not expose set_value() or compatible set_status()."
    )


def _light_set_brightness_sync(device: Any, brightness: Any) -> dict[str, Any]:
    value = max(0, min(100, int(float(brightness))))
    if hasattr(device, "set_brightness_percentage") and callable(
        device.set_brightness_percentage
    ):
        return _normalize_raw_payload(device.set_brightness_percentage(value))
    if hasattr(device, "set_brightness") and callable(device.set_brightness):
        scaled = max(10, min(1000, int(round((value / 100) * 1000))))
        return _normalize_raw_payload(device.set_brightness(scaled))
    raise TuyaClientError("TinyTuya light does not expose brightness controls.")


def _light_set_color_temp_sync(device: Any, color_temp: Any) -> dict[str, Any]:
    value = max(0, min(100, int(float(color_temp))))
    if hasattr(device, "set_colourtemp_percentage") and callable(
        device.set_colourtemp_percentage
    ):
        return _normalize_raw_payload(device.set_colourtemp_percentage(value))
    if hasattr(device, "set_colourtemp") and callable(device.set_colourtemp):
        scaled = max(0, min(1000, int(round((value / 100) * 1000))))
        return _normalize_raw_payload(device.set_colourtemp(scaled))
    raise TuyaClientError("TinyTuya light does not expose color temperature controls.")


def _light_set_color_rgb_sync(device: Any, r: Any, g: Any, b: Any) -> dict[str, Any]:
    red = max(0, min(255, int(float(r))))
    green = max(0, min(255, int(float(g))))
    blue = max(0, min(255, int(float(b))))
    method = getattr(device, "set_colour", None)
    if callable(method):
        return _normalize_raw_payload(method(red, green, blue))
    raise TuyaClientError("TinyTuya light does not expose set_colour().")


def _light_set_mode_sync(device: Any, mode: Any) -> dict[str, Any]:
    method = getattr(device, "set_mode", None)
    if callable(method):
        return _normalize_raw_payload(method(str(mode)))
    raise TuyaClientError("TinyTuya light does not expose set_mode().")


def _fan_set_speed_sync(
    device: Any, speed: Any, speed_dp: int, speed_max: int
) -> dict[str, Any]:
    value = max(0, min(100, int(float(speed))))
    max_value = max(1, int(speed_max))
    raw_value = (
        0
        if value == 0
        else max(1, min(max_value, int(round((value / 100) * max_value))))
    )
    return _normalize_raw_payload(_set_dp_sync(device, str(speed_dp), raw_value))


def _fan_set_oscillate_sync(
    device: Any, oscillating: Any, oscillate_dp: int
) -> dict[str, Any]:
    return _normalize_raw_payload(
        _set_dp_sync(device, str(oscillate_dp), bool(_jsonish_value(oscillating)))
    )


def _fan_set_mode_sync(device: Any, mode: Any, mode_dp: int) -> dict[str, Any]:
    return _normalize_raw_payload(_set_dp_sync(device, str(mode_dp), str(mode)))


def _cover_control_sync(device: Any, control_dp: int, action: str) -> dict[str, Any]:
    return _normalize_raw_payload(_set_dp_sync(device, str(control_dp), action))


def _cover_set_position_sync(
    device: Any, position: Any, position_dp: int
) -> dict[str, Any]:
    value = max(0, min(100, int(float(position))))
    return _normalize_raw_payload(_set_dp_sync(device, str(position_dp), value))


def _climate_set_temperature_sync(
    device: Any, temperature_c: Any, target_dp: int, temp_scale: float
) -> dict[str, Any]:
    value = float(temperature_c)
    raw_value = round(value * max(float(temp_scale), 0.001), 1)
    if float(temp_scale).is_integer():
        raw_value = int(round(raw_value))
    return _normalize_raw_payload(_set_dp_sync(device, str(target_dp), raw_value))


def _climate_set_mode_sync(device: Any, mode: Any, mode_dp: int) -> dict[str, Any]:
    return _normalize_raw_payload(_set_dp_sync(device, str(mode_dp), str(mode)))


def _humidifier_set_humidity_sync(
    device: Any, humidity_percent: Any, target_dp: int, humidity_scale: float
) -> dict[str, Any]:
    value = max(0.0, min(100.0, float(humidity_percent)))
    raw_value = round(value * max(float(humidity_scale), 0.001), 1)
    if float(humidity_scale).is_integer():
        raw_value = int(round(raw_value))
    return _normalize_raw_payload(_set_dp_sync(device, str(target_dp), raw_value))


def _humidifier_set_mode_sync(device: Any, mode: Any, mode_dp: int) -> dict[str, Any]:
    return _normalize_raw_payload(_set_dp_sync(device, str(mode_dp), str(mode)))


def _heartbeat_sync(device: Any) -> None:
    method = getattr(device, "heartbeat", None)
    if callable(method):
        try:
            method(nowait=False)
        except TypeError:
            method()


async def _run_blocking_tuya_call(
    func,
    *args: Any,
    timeout_seconds: float | None = None,
    operation: str = "TinyTuya operation",
    **kwargs: Any,
) -> Any:
    timeout = (
        timeout_seconds if timeout_seconds is not None else tuya_io_timeout_seconds()
    )
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TuyaClientError(
            f"{operation} timed out after {round(float(timeout), 2)}s"
        ) from exc


async def heartbeat_device(device: Any) -> None:
    await _run_blocking_tuya_call(
        _heartbeat_sync,
        device,
        operation="TinyTuya heartbeat",
    )


async def read_device_status(
    config: TuyaDeviceConfig, *, device: Any | None = None
) -> TuyaStatusSnapshot:
    owns_device = device is None
    runtime_device = device or _instantiate_device(config, persist=False)
    try:
        started = time.perf_counter()
        raw = await _run_blocking_tuya_call(
            _status_sync,
            runtime_device,
            operation="TinyTuya status refresh",
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        dps = _extract_dps(raw)
        device_type = normalize_device_type(config.device_type, alias=config.alias)
        power = _extract_power_state(dps, config.switch, device_type)

        metrics: dict[str, Any] = {
            "connected": True,
            "latency_ms": latency_ms,
            "dp_count": len(dps),
            "protocol_version": config.version,
        }
        units: dict[str, Any] = {
            "connected": "bool",
            "latency_ms": "ms",
            "dp_count": "count",
            "protocol_version": "string",
        }

        if power is not None:
            metrics["power"] = power
            units["power"] = "bool"

        if device_type in {"plug", "switch"}:
            _enrich_plug_metrics(dps, metrics, units)
        elif device_type == "light":
            _enrich_light_metrics(dps, metrics, units)
        elif device_type == "fan":
            _enrich_fan_metrics(config, dps, metrics, units)
        elif device_type == "cover":
            _enrich_cover_metrics(config, dps, metrics, units)
        elif device_type == "climate":
            _enrich_climate_metrics(config, dps, metrics, units)
        elif device_type == "humidifier":
            _enrich_humidifier_metrics(config, dps, metrics, units)
        elif device_type == "air_purifier":
            _enrich_air_purifier_metrics(config, dps, metrics, units)

        for dp_name, value in dps.items():
            metric_name = f"dp_{dp_name}"
            metrics[metric_name] = value
            units[metric_name] = _unit_for_value(value)

        return TuyaStatusSnapshot(metrics=metrics, units=units, raw=raw)
    except Exception as exc:
        raise TuyaClientError(f"Unable to query Tuya device status: {exc}") from exc
    finally:
        if owns_device:
            close_device(runtime_device)


async def execute_command(
    config: TuyaDeviceConfig,
    command: str,
    args: Mapping[str, Any] | None = None,
    *,
    device: Any | None = None,
) -> TuyaCommandResult:
    payload = dict(args or {})
    owns_device = device is None
    runtime_device = device or _instantiate_device(config, persist=False)
    try:
        device_type = normalize_device_type(config.device_type, alias=config.alias)
        if command == "refresh":
            raw = await _run_blocking_tuya_call(
                _status_sync,
                runtime_device,
                operation="Tuya refresh command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "turn_on":
            raw = await _run_blocking_tuya_call(
                _power_sync,
                runtime_device,
                enabled=True,
                switch=config.switch,
                operation="Tuya turn_on command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "turn_off":
            raw = await _run_blocking_tuya_call(
                _power_sync,
                runtime_device,
                enabled=False,
                switch=config.switch,
                operation="Tuya turn_off command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_dp":
            dp = str(payload.get("dp") or "").strip()
            if not dp:
                raise TuyaClientError("set_dp requires a dp argument.")
            if "value" not in payload:
                raise TuyaClientError("set_dp requires a value argument.")
            raw = await _run_blocking_tuya_call(
                _set_dp_sync,
                runtime_device,
                dp,
                _jsonish_value(payload["value"]),
                operation="Tuya set_dp command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_brightness":
            if "brightness" not in payload:
                raise TuyaClientError("set_brightness requires a brightness argument.")
            raw = await _run_blocking_tuya_call(
                _light_set_brightness_sync,
                runtime_device,
                payload["brightness"],
                operation="Tuya set_brightness command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_color_temp":
            if "color_temp" not in payload:
                raise TuyaClientError("set_color_temp requires a color_temp argument.")
            raw = await _run_blocking_tuya_call(
                _light_set_color_temp_sync,
                runtime_device,
                payload["color_temp"],
                operation="Tuya set_color_temp command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_color_rgb":
            for key in ("r", "g", "b"):
                if key not in payload:
                    raise TuyaClientError(
                        "set_color_rgb requires r, g, and b arguments."
                    )
            raw = await _run_blocking_tuya_call(
                _light_set_color_rgb_sync,
                runtime_device,
                payload["r"],
                payload["g"],
                payload["b"],
                operation="Tuya set_color_rgb command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_mode":
            if "mode" not in payload:
                raise TuyaClientError("set_mode requires a mode argument.")
            if device_type == "fan":
                if config.fan_mode_dp is None:
                    raise TuyaClientError(
                        "set_mode for fan devices requires fan_mode_dp to be configured or inferred."
                    )
                raw = await _run_blocking_tuya_call(
                    _fan_set_mode_sync,
                    runtime_device,
                    payload["mode"],
                    config.fan_mode_dp,
                    operation="Tuya fan set_mode command",
                )
            elif device_type == "climate":
                if config.climate_mode_dp is None:
                    raise TuyaClientError(
                        "set_mode for climate devices requires climate_mode_dp to be configured or inferred."
                    )
                raw = await _run_blocking_tuya_call(
                    _climate_set_mode_sync,
                    runtime_device,
                    payload["mode"],
                    config.climate_mode_dp,
                    operation="Tuya climate set_mode command",
                )
            elif device_type == "humidifier":
                if config.humidifier_mode_dp is None:
                    raise TuyaClientError(
                        "set_mode for humidifier devices requires humidifier_mode_dp to be configured or inferred."
                    )
                raw = await _run_blocking_tuya_call(
                    _humidifier_set_mode_sync,
                    runtime_device,
                    payload["mode"],
                    config.humidifier_mode_dp,
                    operation="Tuya humidifier set_mode command",
                )
            elif device_type == "air_purifier":
                if config.purifier_mode_dp is None:
                    raise TuyaClientError(
                        "set_mode for air purifier devices requires purifier_mode_dp to be configured or inferred."
                    )
                raw = await _run_blocking_tuya_call(
                    _humidifier_set_mode_sync,
                    runtime_device,
                    payload["mode"],
                    config.purifier_mode_dp,
                    operation="Tuya air purifier set_mode command",
                )
            else:
                raw = await _run_blocking_tuya_call(
                    _light_set_mode_sync,
                    runtime_device,
                    payload["mode"],
                    operation="Tuya light set_mode command",
                )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_fan_speed":
            if "speed" not in payload:
                raise TuyaClientError("set_fan_speed requires a speed argument.")
            speed_dp = config.fan_speed_dp
            speed_max = config.fan_speed_max
            if device_type == "air_purifier":
                speed_dp = config.purifier_speed_dp
                speed_max = config.purifier_speed_max
            raw = await _run_blocking_tuya_call(
                _fan_set_speed_sync,
                runtime_device,
                payload["speed"],
                speed_dp,
                speed_max,
                operation="Tuya set_fan_speed command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_oscillate":
            if "oscillating" not in payload:
                raise TuyaClientError("set_oscillate requires an oscillating argument.")
            if config.fan_oscillate_dp is None:
                raise TuyaClientError(
                    "set_oscillate requires fan_oscillate_dp to be configured or inferred."
                )
            raw = await _run_blocking_tuya_call(
                _fan_set_oscillate_sync,
                runtime_device,
                payload["oscillating"],
                config.fan_oscillate_dp,
                operation="Tuya set_oscillate command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_temperature":
            if "temperature_c" not in payload:
                raise TuyaClientError(
                    "set_temperature requires a temperature_c argument."
                )
            raw = await _run_blocking_tuya_call(
                _climate_set_temperature_sync,
                runtime_device,
                payload["temperature_c"],
                config.climate_target_temp_dp,
                config.climate_temp_scale,
                operation="Tuya set_temperature command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_humidity":
            if "humidity_percent" not in payload:
                raise TuyaClientError(
                    "set_humidity requires a humidity_percent argument."
                )
            raw = await _run_blocking_tuya_call(
                _humidifier_set_humidity_sync,
                runtime_device,
                payload["humidity_percent"],
                config.humidifier_target_humidity_dp,
                config.humidifier_humidity_scale,
                operation="Tuya set_humidity command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "open_cover":
            raw = await _run_blocking_tuya_call(
                _cover_control_sync,
                runtime_device,
                config.cover_control_dp,
                "open",
                operation="Tuya open_cover command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "close_cover":
            raw = await _run_blocking_tuya_call(
                _cover_control_sync,
                runtime_device,
                config.cover_control_dp,
                "close",
                operation="Tuya close_cover command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "stop_cover":
            raw = await _run_blocking_tuya_call(
                _cover_control_sync,
                runtime_device,
                config.cover_control_dp,
                "stop",
                operation="Tuya stop_cover command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        if command == "set_cover_position":
            if "position" not in payload:
                raise TuyaClientError(
                    "set_cover_position requires a position argument."
                )
            if config.cover_position_dp is None:
                raise TuyaClientError(
                    "set_cover_position requires cover_position_dp to be configured or inferred."
                )
            raw = await _run_blocking_tuya_call(
                _cover_set_position_sync,
                runtime_device,
                payload["position"],
                config.cover_position_dp,
                operation="Tuya set_cover_position command",
            )
            return TuyaCommandResult(command=command, raw=raw)
        raise TuyaClientError(f"Unsupported Tuya command: {command}")
    except Exception as exc:
        if isinstance(exc, TuyaClientError):
            raise
        raise TuyaClientError(
            f"Unable to execute Tuya command '{command}': {exc}"
        ) from exc
    finally:
        if owns_device:
            close_device(runtime_device)


def has_cloud_credentials(inputs: Mapping[str, Any]) -> bool:
    return bool(
        inputs.get("api_key") and inputs.get("api_secret") and inputs.get("api_region")
    )


def _discover_cloud_sync(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    module = _require_tinytuya()
    cloud_cls = getattr(module, "Cloud", None)
    if cloud_cls is None:
        raise TuyaClientError(
            "TinyTuya Cloud client is unavailable in this tinytuya build."
        )

    cloud = cloud_cls(
        apiRegion=str(inputs.get("api_region")),
        apiKey=str(inputs.get("api_key")),
        apiSecret=str(inputs.get("api_secret")),
        apiDeviceID=str(inputs.get("api_device_id") or ""),
    )
    response = cloud.getdevices()
    devices: list[dict[str, Any]]
    if isinstance(response, list):
        devices = [item for item in response if isinstance(item, dict)]
    elif isinstance(response, dict):
        possible = (
            response.get("result")
            or response.get("devices")
            or response.get("list")
            or []
        )
        devices = [item for item in possible if isinstance(item, dict)]
    else:
        devices = []

    normalized: list[dict[str, Any]] = []
    for device in devices:
        vendor_id = str(
            device.get("id")
            or device.get("uuid")
            or device.get("uid")
            or device.get("device_id")
            or ""
        ).strip()
        if not vendor_id:
            continue
        alias = str(
            device.get("name")
            or device.get("product_name")
            or device.get("local_name")
            or vendor_id
        )
        product_name = str(device.get("product_name") or "")
        normalized.append(
            _build_discovery_record(
                tuya_device_id=vendor_id,
                host=str(device.get("ip") or device.get("local_ip") or ""),
                alias=alias,
                version=device.get("version") or device.get("ver"),
                category=str(device.get("category") or device.get("biz_type") or "")
                or None,
                product_id=device.get("product_id"),
                product_name=product_name,
                discovery_source="cloud",
            )
        )
    return normalized


def _discover_lan_sync(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    module = _require_tinytuya()
    scan_seconds = int(inputs.get("scan_seconds") or inputs.get("scanSeconds") or 8)
    poll_scan = bool(inputs.get("poll_scan") or inputs.get("pollScan") or False)
    force_scan = bool(inputs.get("force_scan") or inputs.get("forceScan") or False)
    discovered = module.deviceScan(
        verbose=False,
        maxretry=scan_seconds,
        color=False,
        poll=poll_scan,
        forcescan=force_scan,
        byID=False,
    )
    if not isinstance(discovered, dict):
        return []

    devices: list[dict[str, Any]] = []
    for ip, data in discovered.items():
        if not isinstance(data, dict):
            continue
        tuya_device_id = str(
            data.get("gwId") or data.get("id") or data.get("device_id") or ""
        ).strip()
        if not tuya_device_id:
            continue
        product_name = str(data.get("productName") or data.get("product_name") or "")
        alias = str(data.get("name") or product_name or tuya_device_id)
        version = data.get("version")
        dps = data.get("dps") if isinstance(data.get("dps"), dict) else {}
        devices.append(
            _build_discovery_record(
                tuya_device_id=tuya_device_id,
                host=str(data.get("ip") or ip or ""),
                alias=alias,
                version=version,
                category=str(data.get("category") or data.get("biz_type") or "")
                or None,
                product_id=data.get("productKey") or data.get("product_id"),
                product_name=product_name,
                discovery_source="lan_scan",
                dps=dps,
            )
        )
    return devices


def _filter_discovered_devices(
    devices: list[dict[str, Any]],
    inputs: Mapping[str, Any],
) -> list[dict[str, Any]]:
    host_filter = str(inputs.get("host") or "").strip().lower()
    id_filter = (
        str(
            inputs.get("tuya_device_id")
            or inputs.get("tuyaDeviceId")
            or inputs.get("api_device_id")
            or inputs.get("apiDeviceId")
            or ""
        )
        .strip()
        .lower()
    )
    alias_filter = str(inputs.get("alias") or "").strip().lower()

    filtered = devices
    if host_filter:
        filtered = [
            device
            for device in filtered
            if str(device.get("host") or "").strip().lower() == host_filter
        ]
    if id_filter:
        filtered = [
            device
            for device in filtered
            if str(device.get("tuya_device_id") or device.get("device_id") or "")
            .strip()
            .lower()
            == id_filter
        ]
    if alias_filter and not host_filter and not id_filter:
        filtered = [
            device
            for device in filtered
            if alias_filter in str(device.get("alias") or "").strip().lower()
        ]
    return filtered


def _build_manual_candidate(
    inputs: Mapping[str, Any], *, discovery_error: str | None = None
) -> dict[str, Any]:
    tuya_device_id = str(
        inputs.get("tuya_device_id")
        or inputs.get("tuyaDeviceId")
        or inputs.get("api_device_id")
        or inputs.get("apiDeviceId")
        or "tuya-device"
    )
    alias = str(inputs.get("alias") or "Tuya Device")
    return _build_discovery_record(
        tuya_device_id=tuya_device_id,
        host=str(inputs.get("host") or ""),
        alias=alias,
        version=inputs.get("version"),
        category=str(inputs.get("device_type") or "") or None,
        product_name=alias,
        discovery_source="manual",
        discovery_error=discovery_error,
    )


async def discover_devices(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    wants_lan_scan = bool(
        inputs.get("lan_scan")
        or inputs.get("lanScan")
        or inputs.get("scan_seconds")
        or inputs.get("scanSeconds")
    )
    if wants_lan_scan:
        try:
            devices = await _run_blocking_tuya_call(
                _discover_lan_sync,
                inputs,
                timeout_seconds=tuya_discovery_timeout_seconds(),
                operation="TinyTuya LAN discovery",
            )
            devices = _filter_discovered_devices(devices, inputs)
            if devices:
                return devices
        except Exception as exc:
            if has_cloud_credentials(inputs):
                cloud_devices = await _run_blocking_tuya_call(
                    _discover_cloud_sync,
                    inputs,
                    timeout_seconds=tuya_discovery_timeout_seconds(),
                    operation="TinyTuya cloud discovery",
                )
                cloud_devices = _filter_discovered_devices(cloud_devices, inputs)
                if cloud_devices:
                    return cloud_devices
            return [_build_manual_candidate(inputs, discovery_error=str(exc))]

    if has_cloud_credentials(inputs):
        try:
            devices = await _run_blocking_tuya_call(
                _discover_cloud_sync,
                inputs,
                timeout_seconds=tuya_discovery_timeout_seconds(),
                operation="TinyTuya cloud discovery",
            )
            devices = _filter_discovered_devices(devices, inputs)
            if devices:
                return devices
        except Exception as exc:
            return [_build_manual_candidate(inputs, discovery_error=str(exc))]

    return [_build_manual_candidate(inputs)]
