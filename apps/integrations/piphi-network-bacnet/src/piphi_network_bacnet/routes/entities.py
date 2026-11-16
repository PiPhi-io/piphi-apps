from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import PROFILE_ENTITY
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = []
    for entry in entries:
        state = registry.state_snapshots.get(str(entry["config_id"]), {}).get("state", {})
        negotiated_metrics = set((state.get("metrics") or {}).keys())
        negotiated_capabilities = [
            capability
            for capability in PROFILE_ENTITY["capabilities"]
            if capability in {"connected", "refresh"} or capability in negotiated_metrics
        ]
        runtime_entities.append(
            {
                "id": entry["device_id"],
                "name": entry.get("alias") or "Kaiterra SenseEdge Mini",
                "config_id": entry["config_id"],
                "device_id": entry["device_id"],
                "entity_type": PROFILE_ENTITY["entity_type"],
                "capabilities": negotiated_capabilities,
                "available_commands": PROFILE_ENTITY["available_commands"],
                "dashboard": PROFILE_ENTITY["dashboard"],
            }
        )
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
