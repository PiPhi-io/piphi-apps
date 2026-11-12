from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
)
from piphi_runtime_kit_python.fastapi import dispatch_automation_action_from_fastapi

from piphi_network_tp_link.contract.config.routes import run_command_for_device, trigger_refresh
from piphi_network_tp_link.lib.schemas import CommandRequest
from piphi_network_tp_link.lib.store import get_primary_device

router = APIRouter(tags=["command"])

AUTOMATION_COMMANDS = frozenset(
    {
        "feature_action",
        "read_energy",
        "reboot",
        "refresh",
        "set_alias",
        "set_brightness",
        "set_color_temperature",
        "set_feature",
        "set_hue_saturation",
        "toggle",
        "turn_off",
        "turn_on",
    }
)
_ledger_path = Path(
    os.getenv(
        "PIPHI_AUTOMATION_LEDGER_PATH",
        "/.piphinetwork/automation-actions.sqlite3",
    )
)
automation_registry = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(_ledger_path)
)


def _command_target_device_id(payload: CommandRequest) -> str | None:
    target = payload.target if isinstance(payload.target, dict) else {}
    for value in (
        target.get("config_id"),
        target.get("device_id"),
        payload.device_id,
        payload.entity_id,
    ):
        candidate = str(value or "").strip()
        if candidate:
            return candidate
    return None


async def _execute_registered_command(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    try:
        command_result = await run_command_for_device(
            device_id=str(action_request.config_id or action_request.device_id),
            command=action_request.command,
            args=action_request.args,
        )
        refreshed_state = await trigger_refresh(
            str(action_request.config_id or action_request.device_id)
        )
    except HTTPException as exc:
        return AutomationActionResult.failure(
            str(exc.detail),
            retryable=exc.status_code >= 500,
            metadata={"status_code": exc.status_code},
        )

    return AutomationActionResult.success(
        {
            "status": "ok",
            "command": action_request.command,
            "device_id": str(action_request.config_id or action_request.device_id),
            "result": command_result,
            "state": refreshed_state,
        }
    )


for _command_name in sorted(AUTOMATION_COMMANDS):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def execute_command(payload: CommandRequest, request: Request) -> dict[str, Any]:
    command = (payload.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Missing command")
    if command not in AUTOMATION_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {command}")

    device_id = _command_target_device_id(payload)
    if device_id is None:
        primary_device = get_primary_device()
        if primary_device is None:
            raise HTTPException(status_code=404, detail="No configured device found")
        device_id = primary_device["device_id"]

    normalized_payload = {
        **payload.model_dump(mode="python"),
        "command": command,
        "config_id": device_id,
        "device_id": device_id,
    }
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        normalized_payload,
    )
    if not result.ok:
        status_code = int(result.metadata.get("status_code") or 503)
        raise HTTPException(status_code=status_code, detail=result.error)
    return {**result.result, "replayed": result.replayed}
