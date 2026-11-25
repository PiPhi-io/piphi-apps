from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = [
        {
            "id": entry["device_id"],
            "name": entry.get("alias") or "Demo Device",
            "config_id": entry["config_id"],
            "device_id": entry["device_id"],
            "entity_type": FALLBACK_ENTITY["entity_type"],
            "capabilities": [
                item
                for item in FALLBACK_ENTITY["capabilities"]
                if item != "send_key"
                or (
                    isinstance(entry.get("config"), dict)
                    and entry["config"].get("enable_controls") is True
                )
            ],
            "available_commands": [
                item
                for item in FALLBACK_ENTITY["available_commands"]
                if item["id"] != "send_key"
                or (
                    isinstance(entry.get("config"), dict)
                    and entry["config"].get("enable_controls") is True
                )
            ],
            "dashboard": FALLBACK_ENTITY["dashboard"],
        }
        for entry in entries
    ]
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
