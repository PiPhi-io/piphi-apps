from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import capabilities, commands

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    # This package supplies transport to a parent integration. Targets are
    # operational resources, not user-facing PiPhi entities.
    return {"entities": [], "capabilities": capabilities, "commands": commands}
