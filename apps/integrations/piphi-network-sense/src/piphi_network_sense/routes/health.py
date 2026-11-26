from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    snapshots = [
        record.get("state", record)
        for record in getattr(registry, "state_snapshots", {}).values()
    ]
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "stale_configs": sum(bool(item.get("stale")) for item in snapshots),
            "reauth_required_configs": sum(bool(item.get("reauth_required")) for item in snapshots),
            "last_success_at": max(
                (str(item["last_success_at"]) for item in snapshots if item.get("last_success_at")),
                default=None,
            ),
            "last_error_class": next(
                (str(item["error_class"]) for item in reversed(snapshots) if item.get("error_class")),
                None,
            ),
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    return starter.diagnostics_response(
        diagnostics={
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "retention": {
                "timeline_items_per_snapshot": 20,
                "raw_provider_responses": False,
                "credentials_in_diagnostics": False,
            },
            "kind": PROJECT_KIND,
            "api_standing": "unofficial_unsupported",
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
