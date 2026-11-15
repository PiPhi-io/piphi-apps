from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import manager, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Any:
    return starter.health_response(metadata={"scope": "liveness"})


@router.get("/diagnostics")
async def diagnostics() -> Any:
    return starter.diagnostics_response(
        diagnostics={
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            **manager.diagnostics(),
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
