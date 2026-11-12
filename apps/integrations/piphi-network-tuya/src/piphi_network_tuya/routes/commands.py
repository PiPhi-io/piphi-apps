from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_event_ingest_response,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_request,
)

from ..contract import COMMANDS
from ..state import execute_command_for_entry, find_entry, runtime

router = APIRouter(tags=["commands"])
_ledger_path = Path(
    os.getenv(
        "PIPHI_AUTOMATION_LEDGER_PATH",
        "/.piphinetwork/automation-actions.sqlite3",
    )
)
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(_ledger_path)
)


async def _execute_registered_command(
    request: AutomationActionRequest,
) -> dict[str, Any]:
    entry = find_entry(config_id=request.config_id, device_id=request.device_id)
    if entry is None:
        raise ValueError("No configured Tuya device matched the command target")
    result = await execute_command_for_entry(
        entry,
        request.command,
        request.args,
    )
    event = {
        "event_type": "tuya.command.response",
        "device_id": entry["device_id"],
        "config_id": entry["config_id"],
        "payload": {
            "command": request.command,
            "state": result["state"],
        },
    }
    response = build_event_ingest_response(event)
    response_payload = response.model_dump(mode="json")
    return {
        **response_payload,
        "ok": True,
        "command": request.command,
        "device_id": entry["device_id"],
        "state": result["state"],
        "result": result["result"],
    }


for _command_name in sorted(COMMANDS):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    sync_runtime_auth_from_fastapi_request(runtime, request)
    command_name = str(
        payload.get("command") or payload.get("capability_id") or ""
    ).strip()
    if not command_name:
        raise HTTPException(status_code=400, detail="Missing command")
    if command_name not in COMMANDS:
        raise HTTPException(
            status_code=400, detail=f"Unsupported command: {command_name}"
        )

    device_id = str(payload.get("device_id") or "").strip() or None
    config_id = str(payload.get("config_id") or "").strip() or None
    entry = find_entry(config_id=config_id, device_id=device_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="No configured Tuya device matched the command target",
        )

    normalized_payload = {
        **payload,
        "command": command_name,
        "config_id": entry["config_id"],
        "device_id": entry["device_id"],
        "args": payload.get("args") or {},
    }
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        normalized_payload,
    )
    if not result.ok:
        status_code = 503 if result.retryable else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                "ok": False,
                "error": result.error,
                "metadata": result.metadata,
            },
        )
    return {**result.result, "replayed": result.replayed}
