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

from ..mqtt_runtime import ZigbeeMqttClient, ZigbeeMqttError, command_to_mqtt
from ..state import append_runtime_event, commands, registry, runtime
from ..zigbee_devices import available_commands_for

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
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    extras = action_request.model_extra or {}
    device_id = str(action_request.device_id or "demo-device")
    config_id = str(action_request.config_id or device_id)
    entry = registry.get(config_id)
    if entry is None:
        entry = {
            "device_id": device_id,
            "config_id": config_id,
            "mqtt_server": "mqtt://127.0.0.1:1883",
            "mqtt_topic": f"zigbee2mqtt/{device_id}",
            "capabilities": ["refresh"],
        }
        dry_run = True
    else:
        dry_run = bool(extras.get("dry_run") or action_request.args.get("dry_run"))

    if entry.get("exposes"):
        allowed_commands = {
            item["id"]
            for item in available_commands_for(
                list(entry.get("capabilities") or []),
                list(entry.get("exposes") or []),
            )
        }
        if action_request.command not in allowed_commands:
            return AutomationActionResult.failure(
                f"{action_request.command} is not writable for this Zigbee device",
                metadata={"status_code": 400, "error": "command_not_writable"},
            )

    try:
        mqtt_command = command_to_mqtt(
            entry,
            action_request.command,
            action_request.args,
        )
        mqtt_result = await ZigbeeMqttClient(
            server=str(entry.get("mqtt_server") or "mqtt://127.0.0.1:1883"),
        ).publish_json(
            mqtt_command["topic"],
            mqtt_command["payload"],
            dry_run=dry_run,
        )
    except ValueError as exc:
        return AutomationActionResult.failure(
            str(exc),
            metadata={"status_code": 400},
        )
    except ZigbeeMqttError as exc:
        if action_request.command == "refresh":
            mqtt_result = {
                "ok": False,
                "status": "unreachable",
                "topic": mqtt_command["topic"],
                "payload": mqtt_command["payload"],
                "message": str(exc),
            }
        else:
            return AutomationActionResult.failure(
                str(exc),
                retryable=True,
                metadata={"status_code": 502},
            )

    target = extras.get("target") if isinstance(extras.get("target"), dict) else {}
    event = append_runtime_event(
        "zigbee.command.published",
        entry,
        {
            "command": action_request.command,
            "device_id": device_id,
            "entity_id": action_request.entity_id,
            "args": action_request.args,
            "target": target,
            "mqtt": mqtt_result,
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
            "mqtt": mqtt_result,
        }
    )


for _command_name in sorted(commands):
    automation_registry.action(_command_name)(_execute_registered_command)


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    sync_runtime_auth_from_fastapi_request(runtime, request)
    command_name = str(payload.get("command") or payload.get("capability_id") or "").strip()
    if not command_name:
        raise HTTPException(status_code=400, detail="Missing command")
    if command_name not in commands:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {command_name}")

    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    device_id = str(payload.get("device_id") or target.get("device_id") or "demo-device")
    config_id = str(payload.get("config_id") or target.get("config_id") or device_id)
    requirements = payload.get("capability_requirements")
    requested_capabilities = [
        str(item).strip()
        for item in ([payload.get("capability")] + (requirements if isinstance(requirements, list) else []))
        if str(item or "").strip()
    ]
    unsupported_capability = next(
        (
            capability
            for capability in requested_capabilities
            if capability not in {"device.refresh", f"action.{command_name}", command_name}
        ),
        None,
    )
    if unsupported_capability:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "unsupported_capability",
                "message": f"This runtime does not support capability {unsupported_capability}",
            },
        )
    params = payload.get("params") or payload.get("args") or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="Command params must be an object.")
    normalized_payload = {
        **payload,
        "command": command_name,
        "config_id": config_id,
        "device_id": device_id,
        "args": params,
    }
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        normalized_payload,
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
