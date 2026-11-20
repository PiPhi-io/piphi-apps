from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import build_discovery_response, build_event_list_response

from ..contract import CAPABILITIES, COMMANDS, CONFIG_SCHEMA, ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION, PROJECT_DOMAIN, PROJECT_KIND, PROJECT_PRESET

router = APIRouter(tags=["quarantine"])
QUARANTINE = {
    "code": "not_implemented", "installable": False, "ready": False,
    "message": "Daikin Onecta is a quarantined preview; no OAuth or provider API adapter is implemented.",
}

def unavailable() -> None:
    raise HTTPException(status_code=503, detail=QUARANTINE)

@router.get("/health")
async def health():
    return {"ok": True, "status": "quarantined", **QUARANTINE}

@router.get("/diagnostics")
async def diagnostics():
    return {"status": "quarantined", "kind": PROJECT_KIND, **QUARANTINE}

@router.post("/discover")
async def discover():
    return build_discovery_response([])

@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA

@router.post("/config")
@router.post("/config/sync")
async def configure(_payload: dict[str, Any]):
    unavailable()

@router.post("/deconfigure")
@router.post("/deconfigure/{config_id}")
async def deconfigure(config_id: str | None = None):
    return {"ok": True, "removed": False, "config_id": config_id}

@router.get("/state")
async def state():
    return {"states": [], "summary": {"active_config_count": 0}, "availability": QUARANTINE}

@router.get("/contract")
async def contract():
    return {"integration_id": INTEGRATION_ID, "name": INTEGRATION_NAME, "version": INTEGRATION_VERSION,
            "kind": PROJECT_KIND, "preset": PROJECT_PRESET, "domain": PROJECT_DOMAIN,
            "endpoints": ENDPOINTS, "required": REQUIRED_ENDPOINTS, "installable": False}

@router.get("/entities")
async def entities():
    return {"entities": [], "capabilities": CAPABILITIES, "commands": COMMANDS}

@router.get("/events")
async def events():
    return build_event_list_response([])

@router.post("/events/example")
@router.post("/events/device/{config_id}/example")
@router.post("/telemetry/example")
@router.post("/telemetry/device/{config_id}/example")
@router.post("/command")
async def unsupported_operation(config_id: str | None = None):
    unavailable()
