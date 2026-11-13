from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import node_models, registry, starter, supervisors

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "sidecars": {
                config_id: {
                    "connected": supervisor.connected,
                    "event_cursor": supervisor.cursor,
                    "dropped_event_count": supervisor.dropped,
                    "last_error_code": supervisor.last_error,
                    "entity_count": len(node_models.get(config_id, [])),
                }
                for config_id, supervisor in supervisors.items()
            },
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
