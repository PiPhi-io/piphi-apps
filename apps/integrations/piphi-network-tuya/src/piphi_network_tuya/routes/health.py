from __future__ import annotations

from fastapi import APIRouter

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..settings import PROJECT_KIND
from ..state import device_sessions, poll_tasks, registry, starter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    entries = list(registry.entries.values())
    degraded_configs: list[str] = []
    healthy_configs = 0
    for entry in entries:
        snapshot = registry.state_snapshots.get(str(entry.get("config_id")), {})
        state = snapshot.get("state") if isinstance(snapshot, dict) else {}
        if isinstance(state, dict) and state.get("connected") is False:
            degraded_configs.append(str(entry.get("config_id")))
        elif isinstance(state, dict) and state.get("connected") is True:
            healthy_configs += 1
    return starter.health_response(
        metadata={
            "active_configs": len(entries),
            "healthy_configs": healthy_configs,
            "degraded_configs": degraded_configs,
            "poll_task_count": len(poll_tasks),
            "persistent_session_count": len(device_sessions),
        }
    )


@router.get("/diagnostics")
async def diagnostics():
    device_summaries: list[dict[str, object]] = []
    for entry in registry.entries.values():
        config_id = str(entry.get("config_id"))
        snapshot = registry.state_snapshots.get(config_id, {})
        state = snapshot.get("state") if isinstance(snapshot, dict) else {}
        runtime_status = entry.get("runtime_status") if isinstance(entry, dict) else {}
        device_summaries.append(
            {
                "config_id": config_id,
                "device_id": entry.get("device_id"),
                "alias": entry.get("alias"),
                "device_type": entry.get("device_type"),
                "host": entry.get("host"),
                "connected": state.get("connected")
                if isinstance(state, dict)
                else None,
                "last_refresh_at": runtime_status.get("last_refresh_at")
                if isinstance(runtime_status, dict)
                else None,
                "last_success_at": runtime_status.get("last_success_at")
                if isinstance(runtime_status, dict)
                else None,
                "last_failure_at": runtime_status.get("last_failure_at")
                if isinstance(runtime_status, dict)
                else None,
                "consecutive_failures": runtime_status.get("consecutive_failures")
                if isinstance(runtime_status, dict)
                else None,
                "last_error": runtime_status.get("last_error")
                if isinstance(runtime_status, dict)
                else None,
                "polling": config_id in poll_tasks,
                "persistent_session": config_id in device_sessions,
            }
        )
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "kind": PROJECT_KIND,
            "poll_task_count": len(poll_tasks),
            "persistent_session_count": len(device_sessions),
            "devices": device_summaries,
            "contract": {
                "endpoints": ENDPOINTS,
                "required": REQUIRED_ENDPOINTS,
            },
        }
    )
