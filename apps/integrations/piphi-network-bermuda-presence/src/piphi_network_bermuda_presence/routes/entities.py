from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import capabilities, commands, coordinators

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    runtime_entities = []
    for coordinator in coordinators.values():
        for state in coordinator.entity_states():
            runtime_entities.append({
                **state,
                "device_id": state["id"],
                "entity_type": "presence_sensor",
                "capabilities": list(capabilities),
                "available_commands": [],
                "dashboard": {"allowed_widgets": ["tile", "stat"], "default_widget": "tile"},
            })
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
