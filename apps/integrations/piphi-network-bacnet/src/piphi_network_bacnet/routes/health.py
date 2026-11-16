from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import poll_status, poll_tasks, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "active_poll_tasks": len(poll_tasks),
            "connected_configs": sum(
                1 for status in poll_status.values() if status.get("connected")
            ),
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "poll_task_count": len(poll_tasks),
            "poll_status": poll_status,
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
