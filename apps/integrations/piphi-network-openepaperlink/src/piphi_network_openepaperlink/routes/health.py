from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Any:
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics() -> Any:
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "available_config_count": sum(
                1 for entry in registry.entries.values() if entry.get("status") == "available"
            ),
            "stale_config_count": sum(
                1
                for entry in registry.entries.values()
                if entry.get("last_good") and entry.get("status") != "available"
            ),
            "tag_count": sum(
                len(entry.get("tag_ids") or []) for entry in registry.entries.values()
            ),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
