from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import build_event_ingest_response, build_event_list_response

from ..settings import INTEGRATION_ID
from ..state import append_runtime_event, get_entry_or_404, registry, runtime

router = APIRouter(tags=["events"])


@router.get("/events")
async def events():
    return build_event_list_response(registry.recent_events)


@router.post("/events/example")
async def event_example():
    entry = registry.primary_entry() or {
        "device_id": "demo-device",
        "config_id": "demo-device",
        "integration_id": INTEGRATION_ID,
        "container_id": runtime.auth.container_id or None,
    }
    event = append_runtime_event(
        "runtime.event",
        entry,
        {"message": "Example local runtime event"},
    )
    return build_event_ingest_response(event)


@router.post("/events/device/{config_id}/example")
async def device_event_example(config_id: str):
    entry = get_entry_or_404(config_id)
    event = append_runtime_event(
        "runtime.device.checked",
        entry,
        {
            "message": "Example local runtime event for a configured device",
            "host": entry.get("host"),
        },
    )
    return build_event_ingest_response(event)
