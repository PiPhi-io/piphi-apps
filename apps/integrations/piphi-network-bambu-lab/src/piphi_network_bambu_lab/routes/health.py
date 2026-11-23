from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics():
    entries = list(registry.entries.values())
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(entries),
            "availability_counts": {
                status: sum(entry.get("availability") == status for entry in entries)
                for status in ("connecting", "online", "unavailable", "reauth_required")
            },
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
