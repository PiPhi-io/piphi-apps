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

from piphi_network_thinqconnect.contract.config.routes import (
    run_command_for_device,
    trigger_refresh,
)
from piphi_network_thinqconnect.lib.runtime_auth import authorize_runtime_request
from piphi_network_thinqconnect.lib.schemas import CommandRequest
from piphi_network_thinqconnect.lib.store import get_primary_device

router = APIRouter(tags=["command"])
AUTOMATION_COMMANDS = frozenset(
    {
        "disable_eco_friendly",
        "disable_express_mode",
        "disable_express_fridge",
        "disable_power_save",
        "disable_rapid_freeze",
        "disable_remote_control",
        "disable_sabbath_mode",
        "enable_eco_friendly",
        "enable_express_mode",
        "enable_express_fridge",
        "enable_power_save",
        "enable_rapid_freeze",
        "enable_remote_control",
        "enable_sabbath_mode",
        "pause",
        "refresh",
        "set_brightness",
        "set_cook_mode",
        "set_course",
        "set_fan_speed",
        "set_mode",
        "set_target_humidity",
        "set_target_temperature",
        "start",
        "stop",
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


async def _execute_registered_command(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    device_id = str(action_request.device_id or "")
    try:
        if action_request.command == "refresh":
            refreshed_state = await trigger_refresh(device_id)
            return AutomationActionResult.success(
                {
                    "status": "ok",
                    "command": action_request.command,
                    "device_id": device_id,
                    "state": refreshed_state,
                }
            )
        command_result = await run_command_for_device(
            device_id=device_id,
            command=action_request.command,
            args=action_request.args,
        )
        refreshed_state = await trigger_refresh(device_id)
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
            "device_id": device_id,
            "result": command_result,
            "state": refreshed_state,
        }
    )


for _command_name in sorted(AUTOMATION_COMMANDS):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def execute_command(
    payload: CommandRequest,
    request: Request,
) -> dict[str, Any]:
    authorize_runtime_request(request)
    command = (payload.command or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Missing command")
    if command not in AUTOMATION_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {command}")

    device_id = payload.device_id
    if device_id is None:
        primary_device = get_primary_device()
        if primary_device is None:
            raise HTTPException(status_code=404, detail="No configured device found")
        device_id = primary_device["device_id"]

    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        {
            **payload.model_dump(mode="python"),
            "command": command,
            "device_id": device_id,
        },
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
