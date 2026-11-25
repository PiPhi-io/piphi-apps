from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import controllers, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    platform_tools_available = Path(os.getenv("PIPHI_ADB_BINARY", "/usr/bin/adb")).is_file()
    ready_targets = sum(
        controller.lifecycle == "ready" for controller in controllers.values()
    )
    ready = platform_tools_available and (
        not controllers or ready_targets == len(controllers)
    )
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "ready_targets": ready_targets,
            "ready": ready,
            "dependency_state": "ready" if ready else "degraded",
            "platform_tools_available": platform_tools_available,
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
