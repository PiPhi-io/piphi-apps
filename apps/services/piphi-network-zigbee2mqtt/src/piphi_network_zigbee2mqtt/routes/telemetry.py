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
        device_id=str(entry["device_id"]),
        config_id=str(entry["config_id"]),
        container_id=entry.get("container_id"),
        metrics={"connected": True, "temperature_c": 21.4},
        units={"temperature_c": "C"},
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
        device_id=str(entry["device_id"]),
        config_id=str(entry["config_id"]),
        container_id=entry.get("container_id"),
        metrics={
            "connected": True,
            "temperature_c": 21.4,
        },
        units={"temperature_c": "C"},
    )
    return {"status": "queued"}
