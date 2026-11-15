from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import capabilities, commands, manager

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    return {"entities": manager.entities(), "capabilities": capabilities, "commands": commands}
