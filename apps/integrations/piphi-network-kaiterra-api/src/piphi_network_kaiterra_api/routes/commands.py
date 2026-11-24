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
    "air_quality.readings",
    "air_quality.refresh",
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
            f"Kaiterra does not support capability '{unsupported[0]}'",
        )


async def _execute_registered_command(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    extras = action_request.model_extra or {}
    device_id = str(action_request.device_id or "").strip()
    config_id = str(action_request.config_id or "").strip()
    entry = registry.get(config_id) if config_id else None
    if action_request.command == "refresh" and entry is None:
        return AutomationActionResult.failure(
            "refresh requires an exact configured config_id",
            retryable=False,
            metadata={"status_code": 404},
        )
    try:
        refresh_result = None
        if action_request.command in {"refresh", "sync_cloud"}:
            if entry is not None:
                refresh_result = await refresh_entry(entry)
            elif action_request.command == "sync_cloud":
                refresh_result = await refresh_all_entries()
    except Exception as exc:
        return AutomationActionResult.failure(
            str(exc),
            retryable=True,
            metadata={"status_code": 503},
        )
    assert entry is not None or action_request.command == "sync_cloud"
    event_device = entry or {
        "device_id": "all-configured-kaiterra-devices",
        "config_id": "all-configured-kaiterra-devices",
    }
    event = append_runtime_event(
        "runtime.command.received",
        event_device,
        {
            "command": action_request.command,
            "target_scope": "one" if entry is not None else "all",
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
            "target": {"config_id": config_id} if config_id else {},
            "state": refresh_result,
        }
    )


for _command_name in sorted(commands):
    automation_registry.action(_command_name)(_execute_registered_command)
automation_registry.event(
    "device.state_changed",
    label="Kaiterra reading changed",
    data_schema={
        "type": "object",
        "properties": {
            "device_ref": {"type": "string"},
            "changed_metrics": {"type": "array", "items": {"type": "string"}},
            "source_observed_at": {"type": "string"},
        },
        "additionalProperties": False,
    },
)


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    sync_runtime_auth_from_fastapi_request(runtime, request)
    command_name = _resolve_command_name(payload)
    if not command_name:
        _structured_error(400, "missing_command", "Missing command")
    if command_name not in commands:
        _structured_error(400, "unsupported_command", f"Unsupported command: {command_name}")
    _validate_capabilities(payload)

    device_id = str(payload.get("device_id") or _target_value(payload, "device_id") or "").strip()
    config_id = str(payload.get("config_id") or _target_value(payload, "config_id") or "").strip()
    if not config_id and device_id:
        matches = [
            item_id for item_id, entry in registry.entries.items()
            if str(entry.get("device_id")) == device_id
        ]
        if len(matches) > 1:
            _structured_error(409, "ambiguous_target", "device_id matches multiple configurations")
        if matches:
            config_id = matches[0]
    if command_name == "refresh" and not config_id:
        _structured_error(400, "missing_target", "refresh requires an exact config_id or device_id")
    params = payload.get("params") or payload.get("args") or {}
    if not isinstance(params, dict):
        _structured_error(400, "invalid_params", "Command params must be an object")
    if params:
        _structured_error(400, "invalid_params", "Read-only refresh commands accept no parameters")
    if command_name == "sync_cloud" and config_id and registry.get(config_id) is None:
        _structured_error(404, "unknown_target", "sync_cloud target is not configured")
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
