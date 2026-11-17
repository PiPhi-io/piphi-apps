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
    devices = [
        {
            "connected": bool((entry.get("latest_metrics") or {}).get("connected")),
            "stale": (entry.get("latest_metrics") or {}).get("stale"),
            "failure_count": int(entry.get("failure_count", 0)),
        }
        for entry in registry.entries.values()
    ]
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "devices": devices,
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
