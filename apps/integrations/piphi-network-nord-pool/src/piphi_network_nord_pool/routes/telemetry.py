from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..market_client import MarketDataError
from ..state import get_entry_or_404, refresh_config, registry, runtime

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry/example")
async def telemetry_example(request: Request):
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured devices"}
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    try:
        await refresh_config(str(entry["config_id"]))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "queued"}


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str, request: Request):
    entry = get_entry_or_404(config_id)
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    try:
        await refresh_config(str(entry["config_id"]))
    except MarketDataError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "queued"}
