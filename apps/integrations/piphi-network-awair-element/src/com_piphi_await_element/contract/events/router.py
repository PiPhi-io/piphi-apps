from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationEventListResponse,
    build_event_list_response,
)

from com_piphi_await_element.lib.logging import log_event
from com_piphi_await_element.lib.store import registry

router = APIRouter(tags=["events"])


@router.get('/events')
async def get_events() -> IntegrationEventListResponse:
    log_event("events_list", count=len(registry.recent_events))
    return build_event_list_response(registry.recent_events)
