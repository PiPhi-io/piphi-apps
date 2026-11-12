from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


def _connection_entity(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry["device_id"],
        "name": entry.get("alias") or entry.get("device_name") or "Reolink connection",
        "config_id": entry["config_id"],
        "device_id": entry["device_id"],
        "entity_type": "camera",
        "capabilities": FALLBACK_ENTITY["capabilities"],
        "available_commands": FALLBACK_ENTITY["available_commands"],
        "dashboard": FALLBACK_ENTITY["dashboard"],
        "metadata": {
            "host": entry.get("host"),
            "model": entry.get("model"),
            "is_nvr": bool(entry.get("is_nvr")),
        },
    }


def _camera_entity(entry: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    channel_number = int(channel["channel"])
    device_id = f"{entry['device_id']}:channel:{channel_number}"
    return {
        "id": device_id,
        "name": channel["name"],
        "config_id": entry["config_id"],
        "device_id": device_id,
        "parent_device_id": entry["device_id"],
        "entity_type": "camera",
        "capabilities": ["connected", "refresh"],
        "available_commands": FALLBACK_ENTITY["available_commands"],
        "dashboard": FALLBACK_ENTITY["dashboard"],
        "metadata": {
            "channel": channel_number,
            "model": channel.get("model"),
            "firmware": channel.get("firmware"),
            "features": channel.get("features", []),
            "online": bool(channel.get("online")),
            "is_doorbell": bool(channel.get("is_doorbell")),
        },
    }


@router.get("/entities")
async def entities() -> dict[str, Any]:
    runtime_entities: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        runtime_entities.append(_connection_entity(entry))
        runtime_entities.extend(_camera_entity(entry, channel) for channel in entry["channels"])
    return {
        "entities": runtime_entities or [FALLBACK_ENTITY],
        "capabilities": capabilities,
        "commands": commands,
    }
