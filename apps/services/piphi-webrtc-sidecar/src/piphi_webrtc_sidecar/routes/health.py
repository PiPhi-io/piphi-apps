from __future__ import annotations

import httpx
from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..go2rtc import Go2RtcError, go2rtc
from ..media_sessions import media_session_broker
from ..settings import INTEGRATION_ID, INTEGRATION_VERSION, PROJECT_KIND

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    upstream_available = True
    upstream_version = None
    try:
        upstream = await go2rtc.health()
        upstream_version = upstream.get("version")
    except (Go2RtcError, httpx.HTTPError, ValueError):
        upstream_available = False
    return {
        "status": "healthy" if upstream_available else "degraded",
        "service_id": INTEGRATION_ID,
        "version": INTEGRATION_VERSION,
        "go2rtc_available": upstream_available,
        "go2rtc_version": upstream_version,
        "active_sessions": media_session_broker.active_count,
    }


@router.get("/diagnostics")
async def diagnostics():
    return {
        "service_id": INTEGRATION_ID,
        "version": INTEGRATION_VERSION,
        "kind": PROJECT_KIND,
        "active_sessions": media_session_broker.active_count,
        "session_capacity": media_session_broker.capacity,
        "go2rtc_control_plane": "loopback-only",
        "contract": {
            "endpoints": ENDPOINTS,
            "required": REQUIRED_ENDPOINTS,
        },
    }
