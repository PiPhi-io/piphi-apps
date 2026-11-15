from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import coordinators, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(metadata={
        "active_configs": len(registry.ids()),
        "gateway_connected_configs": sum(c.gateway_available for c in coordinators.values()),
        "coverage_degraded": any(c.engine.coverage_degraded or not c.gateway_available for c in coordinators.values()),
    })


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "presence": {config_id: coordinator.engine.diagnostics() | {
                "gateway_available": coordinator.gateway_available,
                "last_error": coordinator.last_error,
                "cursor": coordinator.cursor,
            } for config_id, coordinator in coordinators.items()},
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
