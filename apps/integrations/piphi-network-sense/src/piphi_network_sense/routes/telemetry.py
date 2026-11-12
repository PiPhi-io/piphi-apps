from __future__ import annotations

from fastapi import APIRouter, Request
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..state import get_entry_or_404, registry, runtime, sense_service

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry/example")
async def telemetry_example(request: Request):
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured Sense account"}
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    return {"status": "queued", "state": await sense_service.refresh()}


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str, request: Request):
    entry = get_entry_or_404(config_id)
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    return {"status": "queued", "state": await sense_service.refresh()}
