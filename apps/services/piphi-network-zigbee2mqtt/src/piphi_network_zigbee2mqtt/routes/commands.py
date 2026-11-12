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

from ..state import append_runtime_event, commands, registry, runtime, sidecar_store
from ..zigbee2mqtt_mqtt import Zigbee2MqttMqttClient, resolve_mqtt_settings

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
) -> dict[str, Any]:
    extras = action_request.model_extra or {}
    device_id = str(action_request.device_id or "demo-device")
    config_id = str(action_request.config_id or device_id)
    target = extras.get("target") if isinstance(extras.get("target"), dict) else {}
    entry = registry.get(config_id) or {
        "device_id": device_id,
        "config_id": config_id,
    }
    if action_request.command == "refresh_network_map":
        entry_config = entry.get("config") if isinstance(entry.get("config"), dict) else {}
        mqtt_settings = resolve_mqtt_settings(
            current=sidecar_store.current_config.mqtt if sidecar_store.current_config else None,
            server=entry_config.get("mqtt_server"),
            base_topic=entry_config.get("mqtt_base_topic"),
        )
        routes = bool(action_request.args.get("routes", False))
        topology = await Zigbee2MqttMqttClient(
            mqtt=mqtt_settings,
            timeout_seconds=125.0,
        ).network_map(routes=routes)
        sidecar_store.last_network_map = topology
        topology_state = topology.model_dump(mode="json", exclude={"server"})
        registry.update_state(
            config_id,
            {"connected": True, "zigbee_network_topology": topology_state},
            device_id=device_id,
        )
        return {
            "ok": topology.ok,
            "command": action_request.command,
            "config_id": config_id,
            "device_id": device_id,
            "topology": topology_state,
        }
    event = append_runtime_event(
        "runtime.command.received",
        entry,
        {
            "command": action_request.command,
            "device_id": device_id,
            "entity_id": action_request.entity_id,
            "args": action_request.args,
            "target": target,
        },
    )
    response = build_event_ingest_response(event)
    response_payload = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    return {
        **response_payload,
        "ok": True,
        "command": action_request.command,
        "contract_version": extras.get("contract_version"),
        "device_id": device_id,
        "config_id": config_id,
        "target": target,
        "params": action_request.args,
    }


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
            if capability not in {"device.refresh", "zigbee_network_topology", f"action.{command_name}"}
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
            status_code=503 if result.retryable else 409,
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
