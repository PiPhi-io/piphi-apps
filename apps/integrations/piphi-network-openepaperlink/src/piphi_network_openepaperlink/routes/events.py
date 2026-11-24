from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from piphi_runtime_kit_python import build_event_list_response

from ..state import registry

router = APIRouter(tags=["events"])


@router.get("/events")
async def events() -> Any:
    return build_event_list_response(registry.recent_events)
