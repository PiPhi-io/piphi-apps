from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..security import redact
from ..settings import PROJECT_KIND
from ..state import mqtt_subscription_snapshot, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    subscriptions = mqtt_subscription_snapshot()
    active = len(registry.ids())
    ready = active == 0 or bool(subscriptions.get("running"))
    payload = starter.health_response(
        metadata={
            "active_configs": active,
            "ready": ready,
            "dependency": "zigbee2mqtt-sidecar",
            "dependency_status": "ready" if ready else "unavailable",
        }
    )
    body = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return JSONResponse(status_code=200 if ready else 503, content=body)


@router.get("/diagnostics")
async def diagnostics():
    return redact(starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    ))
