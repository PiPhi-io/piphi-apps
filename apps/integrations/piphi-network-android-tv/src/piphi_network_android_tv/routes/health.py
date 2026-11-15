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
    state = await starter.state.response()
    entries = state.get("entries", {})
    snapshots = [
        entry.get("latest_state", {})
        for entry in entries.values()
        if isinstance(entry, dict)
    ]
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "connected_count": sum(item.get("connected") is True for item in snapshots),
            "reauth_required_count": sum(
                item.get("reauth_required") is True for item in snapshots
            ),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "transport": "android_tv_remote_v2",
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
