from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import AP_ENTITY_TEMPLATE
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities: list[dict[str, Any]] = []
    for entry in entries:
        runtime_entities.append(
            {
                "id": entry["device_id"],
                "name": entry.get("alias") or "OpenEPaperLink access point",
                "config_id": entry["config_id"],
                "device_id": entry["device_id"],
                "entity_type": AP_ENTITY_TEMPLATE["entity_type"],
                "capabilities": AP_ENTITY_TEMPLATE["capabilities"],
                "available_commands": AP_ENTITY_TEMPLATE["available_commands"],
                "dashboard": AP_ENTITY_TEMPLATE["dashboard"],
            }
        )
        for tag_id in entry.get("tag_ids") or []:
            runtime_entities.append(
                {
                    "id": tag_id,
                    "name": f"OpenEPaperLink tag {tag_id[-6:]}",
                    "config_id": entry["config_id"],
                    "device_id": tag_id,
                    "parent_device_id": entry["device_id"],
                    "entity_type": "display_tag",
                    "capabilities": [],
                    "available_commands": [],
                }
            )
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
