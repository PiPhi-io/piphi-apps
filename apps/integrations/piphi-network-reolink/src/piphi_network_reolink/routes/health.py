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
            "model": entry.get("model"),
            "hardware": entry.get("hardware"),
            "firmware": entry.get("firmware"),
            "is_nvr": bool(entry.get("is_nvr")),
            "is_battery": bool(entry.get("is_battery")),
            "availability": entry.get("availability"),
            "last_success_at": entry.get("last_success_at"),
            "last_error_category": entry.get("last_error_category"),
            "camera_count": len(entry.get("channels", [])),
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
