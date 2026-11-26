from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    return {
        "entities": [],
        "ownership": "piphi-network-zigbee",
        "message": "This sidecar supplies transport and does not own PiPhi device entities.",
    }
