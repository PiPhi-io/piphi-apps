from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    assert_behaviors_contract,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .service import SenseRuntimeService
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
automations = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(
        os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")
    )
)

capabilities = CAPABILITIES
commands = COMMANDS
sense_service = SenseRuntimeService(registry=registry, runtime=runtime, telemetry=telemetry)

BEHAVIORS = json.loads(
    (Path(__file__).resolve().parents[1] / "behaviors.json").read_text()
)

# Core projects the telemetry sent by this runtime into this event. Registering
# it here keeps the executable SDK contract aligned with behaviors.json without
# sending a duplicate event alongside telemetry ingestion.
automations.event(
    "device.state_changed",
    label="Sense state changed",
    data_schema={
        "capabilities": {"type": "array"},
        "changed_metrics": {"type": "array"},
    },
)
automations.event(
    "device.power.turned_on",
    label="Sense appliance turned on",
    data_schema={
        "capability": {"type": "string"},
        "transition": {"type": "object"},
    },
)
automations.event(
    "device.power.turned_off",
    label="Sense appliance turned off",
    data_schema={
        "capability": {"type": "string"},
        "transition": {"type": "object"},
    },
)


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "email": config.email,
        "alias": config.alias,
        "config": config.model_dump(mode="json"),
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = str(entry["config_id"])
    previous = registry.get(config_id)
    registry.set(str(entry["config_id"]), entry)
    try:
        await sense_service.configure(config, entry)
    except Exception:
        if previous is None:
            registry.remove(config_id)
        else:
            registry.set(config_id, previous)
        raise
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"email": config.email, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    await sense_service.remove(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"email": entry.get("email"), "alias": entry.get("alias")},
    )
    return True


@automations.action(
    "refresh",
    label="Refresh current power and daily energy from Sense.",
    result_schema={"state": {"type": "object"}},
)
async def refresh_automation(request: AutomationActionRequest) -> dict[str, Any]:
    request_target = getattr(request, "target", None)
    target = request_target if isinstance(request_target, dict) else {}
    device_id = str(request.device_id or target.get("device_id") or "sense-monitor")
    config_id = str(request.config_id or target.get("config_id") or device_id)
    entry = registry.get(config_id) or {
        "device_id": device_id,
        "config_id": config_id,
    }
    event = append_runtime_event(
        "runtime.command.received",
        entry,
        {
            "command": request.command,
            "device_id": device_id,
            "entity_id": request.entity_id,
            "args": request.args,
            "target": target,
        },
    )
    state = await sense_service.refresh(force_trends=True)
    return {
        "event": event,
        "command": request.command,
        "device_id": device_id,
        "config_id": config_id,
        "target": target,
        "params": request.args,
        "state": state,
    }


assert_behaviors_contract(BEHAVIORS, automations)


async def _refresh_all_state() -> None:
    if sense_service.active_config_id is not None:
        await sense_service.refresh(force_trends=True)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
