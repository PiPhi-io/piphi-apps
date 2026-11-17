from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import CAMERA_ENTITY_TEMPLATE
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = [
        {
            "id": entry["device_id"],
            "name": entry.get("alias") or "Camera",
            "config_id": entry["config_id"],
            "device_id": entry["device_id"],
            "entity_type": "camera",
            "capabilities": CAMERA_ENTITY_TEMPLATE["capabilities"],
            "available_commands": CAMERA_ENTITY_TEMPLATE["available_commands"],
            "dashboard": CAMERA_ENTITY_TEMPLATE["dashboard"],
        }
        for entry in entries
    ]
    return {
        "entities": runtime_entities,
        "capabilities": capabilities,
        "commands": commands,
    }
