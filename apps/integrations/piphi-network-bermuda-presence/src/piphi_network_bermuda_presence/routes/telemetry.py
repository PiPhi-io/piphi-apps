from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from piphi_runtime_kit_python import schedule_telemetry_delivery
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..state import coordinators, get_entry_or_404, registry, runtime, telemetry

router = APIRouter(tags=["telemetry"])


def _metrics(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "presence": state["presence"],
        "area_id": state["area_id"],
        "area_name": state["area_name"],
        "estimated_distance_m": state["estimated_distance_m"],
        "distance_raw_m": state["distance_raw_m"],
        "freshness_seconds": state["freshness_seconds"],
        "coverage_degraded": state["coverage_degraded"],
        "topology_revision": state["topology_revision"],
        "area_switch_reason": state["area_switch_reason"],
    }


@router.post("/telemetry/example")
async def telemetry_example(request: Request) -> dict[str, Any]:
    entry = registry.primary_entry()
    if entry is None:
        return {"ok": False, "reason": "no configured devices"}
    return await _queue(str(entry["config_id"]), request)


@router.post("/telemetry/device/{config_id}/example")
async def telemetry_for_device(config_id: str, request: Request) -> dict[str, Any]:
    return await _queue(config_id, request)


async def _queue(config_id: str, request: Request) -> dict[str, Any]:
    entry = get_entry_or_404(config_id)
    coordinator = coordinators.get(config_id)
    if coordinator is None:
        return {"ok": False, "reason": "presence coordinator unavailable"}
    sync_runtime_auth_from_fastapi_payload(runtime, request, entry)
    states = coordinator.entity_states()
    for state in states:
        schedule_telemetry_delivery(
            process_state=runtime.process_state,
            telemetry_client=telemetry,
            auth_context=runtime.auth,
            config_id=config_id,
            device_id=str(state["id"]),
            container_id=entry.get("container_id"),
            metrics=_metrics(state),
            units={"estimated_distance_m": "m", "distance_raw_m": "m", "freshness_seconds": "s"},
        )
    return {"status": "queued", "entity_count": len(states)}
