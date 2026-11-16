from __future__ import annotations

from fastapi import APIRouter

from ..state import get_entry_or_404, poll_once, registry

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry/example")
async def telemetry_example():
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured devices"}
    ok = await poll_once(str(entry["config_id"]))
    return {"ok": ok, "status": "refreshed" if ok else "read_failed"}


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str):
    get_entry_or_404(config_id)
    ok = await poll_once(config_id)
    return {"ok": ok, "status": "refreshed" if ok else "read_failed"}
