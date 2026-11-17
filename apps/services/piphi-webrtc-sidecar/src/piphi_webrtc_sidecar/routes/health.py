from __future__ import annotations

import httpx
from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..go2rtc import Go2RtcError, go2rtc, go2rtc_process
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
    cleanup_degraded = media_session_broker.cleanup_pending_count > 0
    return {
        "status": "healthy" if upstream_available and not cleanup_degraded else "degraded",
        "service_id": INTEGRATION_ID,
        "version": INTEGRATION_VERSION,
        "go2rtc_available": upstream_available,
        "go2rtc_version": upstream_version,
        "process_state": go2rtc_process.state,
        "process_restart_count": go2rtc_process.restart_count,
        "active_sessions": media_session_broker.active_count,
        "cleanup_pending_sessions": media_session_broker.cleanup_pending_count,
    }


@router.get("/diagnostics")
async def diagnostics():
    upstream_available = True
    try:
        await go2rtc.health()
    except (Go2RtcError, httpx.HTTPError, ValueError):
        upstream_available = False
    return {
        "service_id": INTEGRATION_ID,
        "version": INTEGRATION_VERSION,
        "kind": PROJECT_KIND,
        "active_sessions": media_session_broker.active_count,
        "session_capacity": media_session_broker.capacity,
        "cleanup_pending_sessions": media_session_broker.cleanup_pending_count,
        "media_degraded_reason": media_session_broker.degraded_reason,
        "go2rtc_available": upstream_available,
        "process_state": go2rtc_process.state,
        "process_restart_count": go2rtc_process.restart_count,
        "process_error": go2rtc_process.last_error,
        "go2rtc_control_plane": "loopback-only",
        "contract": {
            "endpoints": ENDPOINTS,
            "required": REQUIRED_ENDPOINTS,
        },
    }
