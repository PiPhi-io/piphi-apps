from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import RuntimeEntitiesResponse

from ..state import capabilities, commands, entity_for_entry, entry_for_config, primary_config, registry, starter

router = APIRouter(tags=["entities"])


@router.get("/entities", response_model=RuntimeEntitiesResponse)
async def entities() -> RuntimeEntitiesResponse:
    entries = list(registry.entries.values()) or [entry_for_config(primary_config())]
    return starter.entities_response(
        entities=[entity_for_entry(entry) for entry in entries],
        capabilities=capabilities,
        commands=commands,
    )
