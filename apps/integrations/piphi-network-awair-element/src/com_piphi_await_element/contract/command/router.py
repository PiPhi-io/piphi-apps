from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
)
from piphi_runtime_kit_python.fastapi import dispatch_automation_action_from_fastapi

from com_piphi_await_element.contract.config.routes import trigger_refresh
from com_piphi_await_element.lib.schemas import CommandRequest
from com_piphi_await_element.lib.store import registry

router = APIRouter(tags=["command"])
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(
        Path(os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "/var/lib/piphi/automation-actions.sqlite3"))
    )
)
ALIASES = {"refresh_readings": "refresh", "device.refresh": "refresh"}


def _target(payload: CommandRequest) -> tuple[str, dict]:
    target = payload.target if isinstance(payload.target, dict) else {}
    config_id = str(payload.config_id or target.get("config_id") or "").strip()
    requested_device_id = str(payload.device_id or target.get("device_id") or "").strip()
    if not config_id and requested_device_id:
        config_id = next(
            (key for key, entry in registry.entries.items() if entry.get("device_id") == requested_device_id),
            "",
        )
    if not config_id:
        raise HTTPException(status_code=400, detail={"error": "missing_target"})
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_target"})
    if requested_device_id and requested_device_id != entry.get("device_id"):
        raise HTTPException(status_code=409, detail={"error": "target_mismatch"})
    return config_id, entry


async def _refresh(request: AutomationActionRequest) -> AutomationActionResult:
    try:
        result = await trigger_refresh(str(request.config_id or ""))
    except HTTPException as exc:
        return AutomationActionResult.failure(
            "Awair refresh failed",
            retryable=exc.status_code >= 500,
            metadata={"status_code": exc.status_code},
        )
    return AutomationActionResult.success(result)


automation_registry.action("refresh", label="Refresh Awair readings")(_refresh)


@router.post("/command")
async def execute_command(payload: CommandRequest, request: Request):
    command = ALIASES.get(payload.command.strip(), payload.command.strip())
    if command != "refresh":
        raise HTTPException(status_code=400, detail={"error": "unsupported_command"})
    requested = {item for item in [payload.capability, *payload.capability_requirements] if item}
    if requested - {"refresh", "device.refresh", "air_quality.readings"}:
        raise HTTPException(status_code=400, detail={"error": "unsupported_capability"})
    config_id, entry = _target(payload)
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        {
            **payload.model_dump(mode="python"),
            "command": "refresh",
            "config_id": config_id,
            "device_id": entry["device_id"],
            "args": {},
        },
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail={"error": "refresh_failed", "retryable": result.retryable},
        )
    return {"ok": True, "status": "ok", "command": "refresh", **result.result, "replayed": result.replayed}
