from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY
from ..state import capabilities, commands, registry
from ..zigbee_devices import entity_from_entry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities = [entity_from_entry(entry) for entry in entries] or [FALLBACK_ENTITY]
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
