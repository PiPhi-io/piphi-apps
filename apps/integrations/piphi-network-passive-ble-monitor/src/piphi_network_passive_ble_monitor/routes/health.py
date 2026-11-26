from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import diagnostic_snapshot, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    snapshot = diagnostic_snapshot()
    ready = not snapshot or all(item["receiver_healthy"] for item in snapshot.values())
    return starter.health_response(metadata={"ready": ready, "active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "ble_consumers": diagnostic_snapshot(),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
