from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import plex_service, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(metadata={"active_configs": len(registry.ids()), "provider_instances": len(plex_service.instances())})


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "provider_instances": plex_service.instances(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
