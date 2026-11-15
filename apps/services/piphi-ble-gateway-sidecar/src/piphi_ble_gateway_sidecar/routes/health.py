from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..gateway import gateway
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    detail = await gateway.diagnostics()
    return starter.health_response(metadata={"active_configs": len(registry.ids()), **detail})


@router.get("/diagnostics")
async def diagnostics():
    ble = await gateway.diagnostics()
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "ble": ble,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
