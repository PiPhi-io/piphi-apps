from __future__ import annotations

from fastapi import APIRouter

from ..bridge import bridge_supervisor
from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS, SERVICE_CAPABILITY
from ..settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION, UPSTREAM_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    status = bridge_supervisor.status()
    return {
        "status": "healthy" if not status["configured"] or status["running"] else "degraded",
        "integration_id": INTEGRATION_ID,
        "name": INTEGRATION_NAME,
        "version": INTEGRATION_VERSION,
        "service": status,
    }


@router.get("/diagnostics")
async def diagnostics() -> dict[str, object]:
    return {
        "integration_id": INTEGRATION_ID,
        "version": INTEGRATION_VERSION,
        "upstream": {"name": "docker-wyze-bridge", "version": UPSTREAM_VERSION},
        "service": bridge_supervisor.status(),
        "contract": {"endpoints": ENDPOINTS, "required": REQUIRED_ENDPOINTS},
    }


@router.get("/contract")
async def contract() -> dict[str, object]:
    return {
        "integration_id": INTEGRATION_ID,
        "name": INTEGRATION_NAME,
        "version": INTEGRATION_VERSION,
        "kind": "platform_service",
        "capabilities": [SERVICE_CAPABILITY],
        "endpoints": ENDPOINTS,
        "required": REQUIRED_ENDPOINTS,
    }
