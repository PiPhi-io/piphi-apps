from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    IntegrationCommandRequest,
    SQLiteAutomationIdempotencyStore,
)
from piphi_runtime_kit_python.fastapi import dispatch_automation_action_from_fastapi
from pydantic import ValidationError

from ..sensors import preflight_target
from ..state import (
    I2CSensorRuntimeConfig,
    append_runtime_event,
    config_to_sensor_config,
    primary_config,
    read_state,
    registry,
    run_hardware_operation,
    schedule_state_telemetry,
    unavailable_state,
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


async def _refresh_sensor(
    action_request: AutomationActionRequest,
) -> AutomationActionResult:
    config_id = (
        action_request.entity_id
        or action_request.device_id
        or (registry.ids()[0] if registry.ids() else primary_config().id)
    )
    entry = registry.get(config_id) or registry.primary_entry()
    raw_config = entry.get("config") if entry else None
    if isinstance(raw_config, dict) and raw_config.get("adapter", "mock") != "mock":
        return AutomationActionResult.failure(
            "I2C operation failed (physical_backend_not_deployable)",
            retryable=False,
            metadata={"status_code": 400},
        )
    try:
        config = I2CSensorRuntimeConfig.model_validate(entry["config"]) if entry else primary_config()
    except ValidationError:
        return AutomationActionResult.failure(
            "I2C operation failed (invalid_or_unsupported_config)",
            retryable=False,
            metadata={"status_code": 400},
        )
    previous = registry.state_snapshots.get(config.id, {}).get("state", {}) if entry else {}
    recovering = bool(previous and not previous.get("connected", False))
    if entry and recovering:
        registry.update_state(
            config.id,
            {"connected": False, "availability": "recovering", "stale": True, "error_class": None},
            device_id=entry.get("device_id"),
        )
    try:
        sensor_config = config_to_sensor_config(config)
        preflight_target(sensor_config)
        state_payload = await run_hardware_operation(sensor_config, read_state)
        state_payload = {**state_payload, "availability": "available", "stale": False, "error_class": None}
    except Exception as exc:
        if entry:
            failure_state = unavailable_state(exc, previous=previous)
            registry.update_state(
                config.id,
                failure_state,
                device_id=(entry or {}).get("device_id"),
            )
            schedule_state_telemetry(entry, {"connected": False})
            append_runtime_event(
                "i2c.sensor.refresh_failed",
                entry,
                {"command": action_request.command, "error_class": failure_state["error_class"]},
            )
        return AutomationActionResult.failure(
            f"I2C operation failed ({unavailable_state(exc)['error_class']})",
            retryable=unavailable_state(exc)["error_class"] in {"timeout", "unavailable", "busy_or_driver_owned", "io_error"},
            metadata={"status_code": 503},
        )
    registry.update_state(config.id, state_payload, device_id=(entry or {}).get("device_id"))
    if entry:
        schedule_state_telemetry(entry, state_payload)
        append_runtime_event(
            "i2c.sensor.recovered" if recovering else "i2c.sensor.refreshed",
            entry,
            {"command": action_request.command},
        )
    return AutomationActionResult.success({"ok": True, "state": state_payload})


automation_registry.action("refresh")(_refresh_sensor)


@router.post("/command")
async def command(
    payload: IntegrationCommandRequest,
    request: Request,
) -> dict[str, object]:
    if payload.command != "refresh":
        raise HTTPException(status_code=400, detail=f"Unsupported command: {payload.command}")
    result = await dispatch_automation_action_from_fastapi(
        automation_registry,
        request,
        payload,
    )
    if not result.ok:
        raise HTTPException(
            status_code=int(result.metadata.get("status_code") or 503),
            detail=result.error,
        )
    return {**result.result, "replayed": result.replayed}
