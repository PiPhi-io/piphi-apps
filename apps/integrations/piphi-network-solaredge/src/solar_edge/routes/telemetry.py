from __future__ import annotations

from fastapi import APIRouter, Request
from piphi_runtime_kit_python import schedule_telemetry_delivery
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..state import get_entry_or_404, registry, runtime, telemetry

router = APIRouter(tags=["telemetry"])


@router.post("/telemetry/example")
async def telemetry_example(request: Request):
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured devices"}
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics={"connected": True, "production_power_w": 2140.0},
        units={"production_power_w": "W"},
    )
    return {"status": "queued"}


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str, request: Request):
    entry = get_entry_or_404(config_id)
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics={
            "connected": True,
            "production_power_w": 2140.0,
        },
        units={"production_power_w": "W"},
    )
    return {"status": "queued"}
