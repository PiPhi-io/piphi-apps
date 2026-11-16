from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, solaredge_service, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "freshness": solaredge_service.freshness_summary(),
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "poll_status": {
                "read_failure_count": solaredge_service.freshness_summary()["read_failure_count"],
                "last_error_classes": sorted({
                    str(status["last_error"])
                    for status in solaredge_service.poll_status.values()
                    if status.get("last_error")
                }),
            },
            "freshness": solaredge_service.freshness_summary(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
