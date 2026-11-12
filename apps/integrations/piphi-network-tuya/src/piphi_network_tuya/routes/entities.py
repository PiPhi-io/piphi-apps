from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from piphi_runtime_kit_python import build_entities_response

from ..contract import (
    AIR_PURIFIER_ENTITY_CAPABILITIES,
    AIR_PURIFIER_FALLBACK_ENTITY,
    CAPABILITIES,
    CLIMATE_ENTITY_CAPABILITIES,
    CLIMATE_FALLBACK_ENTITY,
    COMMANDS,
    COVER_ENTITY_CAPABILITIES,
    COVER_FALLBACK_ENTITY,
    FAN_ENTITY_CAPABILITIES,
    FAN_FALLBACK_ENTITY,
    GENERIC_FALLBACK_ENTITY,
    HUMIDIFIER_ENTITY_CAPABILITIES,
    HUMIDIFIER_FALLBACK_ENTITY,
    LIGHT_ENTITY_CAPABILITIES,
    LIGHT_FALLBACK_ENTITY,
    PLUG_ENTITY_CAPABILITIES,
    PLUG_FALLBACK_ENTITY,
    SWITCH_ENTITY_CAPABILITIES,
)
from ..state import registry

router = APIRouter(tags=["entities"])


def _command_definitions(names: list[str]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for name in names:
        definition = COMMANDS.get(name, {})
        command = {
            "id": name,
            "label": name.replace("_", " ").title(),
            "kind": "action",
        }
        if definition.get("args_schema"):
            command["args_schema"] = definition["args_schema"]
        commands.append(command)
    return commands


def _entity_profile(device_type: str) -> dict[str, Any]:
    normalized = str(device_type or "device").lower()
    if normalized == "light":
        return {
            "device_class": "light",
            "entity_type": "light",
            "capabilities": LIGHT_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_brightness",
                    "set_color_temp",
                    "set_color_rgb",
                    "set_mode",
                    "set_dp",
                ]
            ),
            "dashboard": LIGHT_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "plug":
        return {
            "device_class": "outlet",
            "entity_type": "switch",
            "capabilities": PLUG_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                ["refresh", "turn_on", "turn_off", "set_dp"]
            ),
            "dashboard": PLUG_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "fan":
        return {
            "device_class": "fan",
            "entity_type": "fan",
            "capabilities": FAN_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_fan_speed",
                    "set_oscillate",
                    "set_mode",
                    "set_dp",
                ]
            ),
            "dashboard": FAN_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "cover":
        return {
            "device_class": "cover",
            "entity_type": "cover",
            "capabilities": COVER_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "open_cover",
                    "close_cover",
                    "stop_cover",
                    "set_cover_position",
                    "set_dp",
                ]
            ),
            "dashboard": COVER_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "climate":
        return {
            "device_class": "climate",
            "entity_type": "climate",
            "capabilities": CLIMATE_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_temperature",
                    "set_mode",
                    "set_dp",
                ]
            ),
            "dashboard": CLIMATE_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "humidifier":
        return {
            "device_class": "humidifier",
            "entity_type": "humidifier",
            "capabilities": HUMIDIFIER_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_humidity",
                    "set_mode",
                    "set_dp",
                ]
            ),
            "dashboard": HUMIDIFIER_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "air_purifier":
        return {
            "device_class": "air_purifier",
            "entity_type": "air_purifier",
            "capabilities": AIR_PURIFIER_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                [
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_fan_speed",
                    "set_mode",
                    "set_dp",
                ]
            ),
            "dashboard": AIR_PURIFIER_FALLBACK_ENTITY["dashboard"],
        }
    if normalized == "switch":
        return {
            "device_class": "switch",
            "entity_type": "switch",
            "capabilities": SWITCH_ENTITY_CAPABILITIES,
            "available_commands": _command_definitions(
                ["refresh", "turn_on", "turn_off", "set_dp"]
            ),
            "dashboard": PLUG_FALLBACK_ENTITY["dashboard"],
        }
    return {
        "device_class": "device",
        "entity_type": "device",
        "capabilities": SWITCH_ENTITY_CAPABILITIES,
        "available_commands": _command_definitions(
            ["refresh", "turn_on", "turn_off", "set_dp"]
        ),
        "dashboard": GENERIC_FALLBACK_ENTITY["dashboard"],
    }


def _fallback_entity() -> dict[str, Any]:
    return PLUG_FALLBACK_ENTITY


def _entity_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry.get("config_id"))
    snapshot = registry.state_snapshots.get(config_id, {})
    latest_state = snapshot.get("state") if isinstance(snapshot, dict) else {}
    profile = _entity_profile(str(entry.get("device_type") or "device"))
    return {
        "id": str(entry.get("device_id") or entry.get("tuya_device_id") or config_id),
        "name": str(entry.get("alias") or entry.get("tuya_device_id") or "Tuya Device"),
        "config_id": config_id,
        "device_id": str(entry.get("device_id") or config_id),
        "device_type": str(entry.get("device_type") or "device"),
        "device_class": profile["device_class"],
        "entity_type": profile["entity_type"],
        "capabilities": profile["capabilities"],
        "available_commands": profile["available_commands"],
        "dashboard": profile["dashboard"],
        "metadata": {
            "host": entry.get("host"),
            "tuya_device_id": entry.get("tuya_device_id"),
            "protocol_version": entry.get("protocol_version"),
            "latest_state": latest_state or {},
        },
    }


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = [_entity_for_entry(entry) for entry in entries] or [
        _fallback_entity()
    ]
    return build_entities_response(
        entities=runtime_entities,
        capabilities=CAPABILITIES,
        commands=COMMANDS,
    ).model_dump(exclude_none=True)
