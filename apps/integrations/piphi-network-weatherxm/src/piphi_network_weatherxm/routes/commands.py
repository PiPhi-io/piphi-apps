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
    build_event_ingest_response,
)
from piphi_runtime_kit_python.fastapi import (
    dispatch_automation_action_from_fastapi,
    sync_runtime_auth_from_fastapi_request,
)

from ..state import (
    append_runtime_event,
    commands,
    refresh_all_entries,
    refresh_entry,
    registry,
    runtime,
)

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

COMMAND_ALIASES = {
    "refresh_readings": "refresh",
    "device.refresh": "refresh",
}
SUPPORTED_CAPABILITIES = {
    "action.refresh",
    "action.sync_cloud",
    "device.refresh",
    "weather.refresh",
    "weather.current",
    "weather.forecast",
}


def _payload_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _structured_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"ok": False, "error": code, "message": message},
    )


def _target_value(payload: dict[str, Any], key: str) -> str:
    target = _payload_dict(payload.get("target"))
    return str(target.get(key) or "").strip()


def _resolve_command_name(payload: dict[str, Any]) -> str:
    raw_command = str(payload.get("command") or payload.get("capability_id") or "").strip()
    return COMMAND_ALIASES.get(raw_command, raw_command)


def _validate_capabilities(payload: dict[str, Any]) -> None:
    requirements = payload.get("capability_requirements")
    requested = [
        str(item).strip()
        for item in ([payload.get("capability")] + (requirements if isinstance(requirements, list) else []))
        if str(item or "").strip()
    ]
    unsupported = [capability for capability in requested if capability not in SUPPORTED_CAPABILITIES]
    if unsupported:
        _structured_error(
            400,
            "unsupported_capability",
            f"WeatherXM does not support capability '{unsupported[0]}'",
        )


async def _execute_registered_command(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    extras = action_request.model_extra or {}
    device_id = str(action_request.device_id or "demo-device")
    config_id = str(action_request.config_id or device_id)
    entry = registry.get(config_id) or {
        "device_id": device_id,
        "config_id": config_id,
    }
    try:
        refreshed_state = None
        if action_request.command == "sync_cloud":
            refreshed_state = await refresh_all_entries()
        elif action_request.command == "refresh" and registry.get(config_id):
            refreshed_state = await refresh_entry(entry)
    except Exception as exc:
        return AutomationActionResult.failure(
            str(exc),
            retryable=True,
            metadata={"status_code": 503},
        )
    target = extras.get("target") if isinstance(extras.get("target"), dict) else {}
    event = append_runtime_event(
        "runtime.command.received",
        entry,
        {
            "command": action_request.command,
            "device_id": device_id,
            "entity_id": action_request.entity_id,
            "args": action_request.args,
            "target": target,
            "refreshed": refreshed_state is not None,
        },
    )
    response = build_event_ingest_response(event)
    response_payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    return AutomationActionResult.success(
        {
            **response_payload,
            "ok": True,
            "command": action_request.command,
            "contract_version": extras.get("contract_version"),
            "device_id": device_id,
            "config_id": config_id,
            "target": target,
            "params": action_request.args,
            "state": refreshed_state,
        }
    )


for _command_name in sorted(commands):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    sync_runtime_auth_from_fastapi_request(runtime, request)
    command_name = _resolve_command_name(payload)
    if not command_name:
        _structured_error(400, "missing_command", "Missing command")
    if command_name not in commands:
        _structured_error(400, "unsupported_command", f"Unsupported command: {command_name}")
    _validate_capabilities(payload)

    device_id = str(payload.get("device_id") or _target_value(payload, "device_id") or "demo-device")
    config_id = str(payload.get("config_id") or _target_value(payload, "config_id") or device_id)
    params = payload.get("params") or payload.get("args") or {}
    if not isinstance(params, dict):
        _structured_error(400, "invalid_params", "Command params must be an object")
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        {
            **payload,
            "command": command_name,
            "config_id": config_id,
            "device_id": device_id,
            "args": params,
        },
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
