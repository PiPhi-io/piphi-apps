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

from ..state import (
    I2CSensorRuntimeConfig,
    append_runtime_event,
    config_to_sensor_config,
    primary_config,
    registry,
    read_state,
    schedule_state_telemetry,
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
    config = I2CSensorRuntimeConfig.model_validate(entry["config"]) if entry else primary_config()
    try:
        state_payload = read_state(config_to_sensor_config(config))
    except Exception as exc:
        if entry:
            registry.update_state(
                config.id,
                {"connected": False, "error": str(exc)},
                device_id=(entry or {}).get("device_id"),
            )
            schedule_state_telemetry(entry, {"connected": False})
            append_runtime_event(
                "i2c.sensor.refresh_failed",
                entry,
                {"command": action_request.command, "error": str(exc)},
            )
        return AutomationActionResult.failure(
            str(exc),
            retryable=True,
            metadata={"status_code": 503},
        )
    registry.update_state(config.id, state_payload, device_id=(entry or {}).get("device_id"))
    if entry:
        schedule_state_telemetry(entry, state_payload)
        append_runtime_event(
            "i2c.sensor.refreshed",
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
