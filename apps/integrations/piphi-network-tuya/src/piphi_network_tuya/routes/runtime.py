from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..contract import ENDPOINTS, REQUIRED_ENDPOINTS
from ..metadata import build_behaviors, build_manifest
from ..settings import (
    INTEGRATION_ID,
    INTEGRATION_NAME,
    INTEGRATION_VERSION,
    PROJECT_DOMAIN,
    PROJECT_KIND,
    PROJECT_PRESET,
)
from ..state import device_sessions, poll_tasks, registry, sanitize_entry, starter

router = APIRouter(tags=["runtime"])
_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "manifest.json"
_BEHAVIORS_PATH = Path(__file__).resolve().parents[2] / "behaviors.json"


@router.get("/manifest.json")
async def manifest() -> dict[str, Any]:
    return build_manifest()


@router.get("/manifest.static.json")
async def manifest_static() -> dict[str, Any]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


@router.get("/behaviors.json")
async def behaviors() -> dict[str, Any]:
    return build_behaviors()


@router.get("/behaviors.static.json")
async def behaviors_static() -> dict[str, Any]:
    return json.loads(_BEHAVIORS_PATH.read_text(encoding="utf-8"))


@router.get("/state")
async def state(
    refresh: bool = Query(default=False),
    refresh_request_id: str | None = Query(default=None),
) -> dict[str, Any]:
    try:
        state_payload = await starter.state.response(
            refresh=refresh,
            refresh_request_id=refresh_request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = {
        "summary": {
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "poll_task_count": len(poll_tasks),
            "persistent_session_count": len(device_sessions),
        },
        "entries": {
            config_id: sanitize_entry(entry)
            for config_id, entry in registry.entries.items()
        },
        "state_snapshots": registry.state_snapshots,
    }
    if "refresh" in state_payload:
        payload["refresh"] = state_payload["refresh"]
    return payload


@router.get("/contract")
async def contract() -> dict[str, Any]:
    return {
        "integration_id": INTEGRATION_ID,
        "name": INTEGRATION_NAME,
        "version": INTEGRATION_VERSION,
        "kind": PROJECT_KIND,
        "preset": PROJECT_PRESET,
        "domain": PROJECT_DOMAIN,
        "endpoints": ENDPOINTS,
        "required": REQUIRED_ENDPOINTS,
    }
