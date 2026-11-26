from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..mqtt_gateway import mqtt_gateway
from ..security import redact
from ..settings import PROJECT_KIND
from ..state import registry, sidecar_store, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    snapshot = sidecar_store.snapshot()
    gateway = mqtt_gateway.snapshot()
    bridge_status = gateway["availability"]["bridge"]["status"]
    ready = not snapshot.configured or (
        gateway["status"] == "running" and bridge_status == "online"
    )
    payload = starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "bridge_configured": snapshot.configured,
            "bridge_runtime": snapshot.runtime,
            "adapter_path": snapshot.adapter_path,
            "ready": ready,
            "broker_status": gateway["availability"]["broker"]["status"],
            "bridge_status": bridge_status,
            "remote_coordinator_ownership": (
                "unverified" if str(snapshot.adapter_path or "").startswith(("tcp://", "socket://")) else "local_claimed"
            ),
        }
    )
    body = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    return JSONResponse(status_code=200 if ready else 503, content=redact(body))


@router.get("/diagnostics")
async def diagnostics():
    return redact(starter.diagnostics_response(
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
    ))
