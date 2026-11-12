from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY
from ..state import capabilities, commands, plex_service, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = [
        {
            "id": instance["id"],
            "name": instance["name"],
            "config_id": instance["config_id"],
            "device_id": instance["machine_id"],
            "device_class": "media_server",
            "entity_type": "media_library",
            "capabilities": FALLBACK_ENTITY["capabilities"],
            "available_commands": FALLBACK_ENTITY["available_commands"],
            "dashboard": FALLBACK_ENTITY["dashboard"],
        }
        for entry in entries
        for instance in plex_service.instances(str(entry["config_id"]))
    ] or [FALLBACK_ENTITY]
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
