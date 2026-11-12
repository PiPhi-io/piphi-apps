from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, sidecar_store, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    snapshot = sidecar_store.snapshot()
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "bridge_configured": snapshot.configured,
            "bridge_runtime": snapshot.runtime,
            "adapter_path": snapshot.adapter_path,
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "bridge": sidecar_store.snapshot().model_dump(mode="json"),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
