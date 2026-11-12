from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationEventIngestResponse,
    IntegrationEventListResponse,
    IntegrationEventRequest,
    build_event_ingest_response,
    build_event_list_response,
    format_event_log,
)

from piphi_network_thinqconnect.lib.logging import logger
from piphi_network_thinqconnect.lib.store import append_event, registry


router = APIRouter(tags=["events"])


@router.get("/events")
async def get_events() -> IntegrationEventListResponse:
    logger.info("events_list count=%s", len(registry.recent_events))
    return build_event_list_response(registry.recent_events)


@router.post("/events")
async def ingest_event(payload: IntegrationEventRequest) -> IntegrationEventIngestResponse:
    event = append_event(payload.model_dump())
    logger.info(format_event_log(payload))
    return build_event_ingest_response(event)
