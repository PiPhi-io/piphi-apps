from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> Any:
    return starter.health_response(metadata={"active_configs": len(registry.ids())})


@router.get("/diagnostics")
async def diagnostics() -> Any:
    firewalls = [
        {
            "connected": (entry.get("latest_state") or {}).get("connected", False),
            "pfsense_version": (entry.get("latest_state") or {}).get("pfsense_version"),
            "rest_api_version": (entry.get("latest_state") or {}).get(
                "rest_api_version"
            ),
            "last_updated": entry.get("last_updated"),
            "endpoint_errors": (entry.get("latest_state") or {}).get(
                "endpoint_errors", {}
            ),
            "error": (entry.get("latest_state") or {}).get("error"),
            "read_only": (entry.get("connection") or {}).get("read_only", True),
        }
        for entry in registry.entries.values()
    ]
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "firewalls": firewalls,
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "upstream_api": "pfSense REST API v2 (community pfREST package)",
            "access_mode": (
                "read-only"
                if all(item["read_only"] for item in firewalls)
                else "monitoring-with-opt-in-operations"
            ),
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
