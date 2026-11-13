from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import all_entities, capabilities, commands

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    return {"entities": all_entities(), "capabilities": capabilities, "commands": commands}
