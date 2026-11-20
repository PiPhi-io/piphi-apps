from fastapi import APIRouter, Request
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..state import get_entry_or_404, refresh_entry, registry, runtime

router = APIRouter(tags=["telemetry"])


async def _queue_current_state(entry, request: Request):
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    state = await refresh_entry(entry)
    return {
        "status": "queued",
        "config_id": entry["config_id"],
        "climate_count": state.get("climate_count", 0),
    }


@router.post("/telemetry/example")
async def telemetry_example(request: Request):
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured accounts"}
    return await _queue_current_state(entry, request)


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str, request: Request):
    return await _queue_current_state(get_entry_or_404(config_id), request)
