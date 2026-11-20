from fastapi import APIRouter
from piphi_runtime_kit_python import build_discovery_response

from ..contract import CONFIG_SCHEMA
from ..state import registry, store

router = APIRouter(tags=["runtime"])


@router.get("/health")
async def health():
    degraded = sum(
        1
        for snapshot in registry.state_snapshots.values()
        if snapshot.get("state", {}).get("detector_status") != "healthy"
    )
    return {
        "ok": True,
        "status": "degraded" if degraded else "healthy",
        "active_config_count": len(registry.ids()),
        "degraded_config_count": degraded,
    }


@router.get("/diagnostics")
async def diagnostics():
    return {
        "status": "ready",
        "schema_version": store.schema_version(),
        "active_config_count": len(registry.ids()),
        "recent_event_count": len(registry.recent_events),
    }


@router.post("/discover")
async def discover():
    return build_discovery_response([])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
