from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import IntegrationEventListResponse, build_event_list_response

from ..state import registry

router = APIRouter(tags=["events"])


@router.get("/events", response_model=IntegrationEventListResponse)
async def events(limit: int = 50) -> IntegrationEventListResponse:
    return build_event_list_response(registry.recent_events[-limit:])
