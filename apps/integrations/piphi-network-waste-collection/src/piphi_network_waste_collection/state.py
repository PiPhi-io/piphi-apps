from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .manual_schedule import resolve_manual_pickup
from .schemas import DeviceConfig
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


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"api_key"}),
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
    registry.set(entry["config_id"], entry)
    registry.update_state(
        entry["config_id"],
        {
            "connected": False,
            "host": config.host,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    await refresh_entry(entry)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config = DeviceConfig.model_validate(entry["config"])
    try:
        pickup = resolve_manual_pickup(
            config.next_collection_date or "",
            config.collection_type or "",
            config.schedule_timezone or "UTC",
        )
    except ValueError:
        state = {"connected": False, "reason": "manual_schedule_unavailable"}
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state
    metrics = {
        "connected": True,
        "next_collection_date": pickup.collection_date,
        "next_collection_type": pickup.collection_type,
        "days_until_collection": pickup.days_until_collection,
    }
    registry.update_state(entry["config_id"], metrics, device_id=entry["device_id"])
    entry["next_poll_at"] = time.monotonic() + 900
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={"days_until_collection": "days"},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: (
                completed.exception() if not completed.cancelled() else None
            )
        )
    return metrics


async def poll_manual_schedules() -> None:
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for entry in list(registry.entries.values()):
            if entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 900
            await refresh_entry(entry)


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(
                request.device_id or target.get("device_id") or "demo-device"
            )
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id)
            if entry is None:
                raise ValueError("Unknown configured collection schedule")
            metrics = await refresh_entry(entry)
            if not metrics.get("connected"):
                raise RuntimeError("Collection schedule is unavailable")
            event = append_runtime_event(
                "runtime.command.received",
                entry,
                {
                    "command": _command_name,
                    "device_id": device_id,
                    "entity_id": request.entity_id,
                    "args": request.args,
                    "target": target,
                },
            )
            return {
                "event": event,
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "target": target,
                "params": request.args,
                "days_until_collection": metrics["days_until_collection"],
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
async def _refresh_all_state() -> None:
    for entry_id in registry.ids():
        entry = registry.get(entry_id)
        if entry is not None:
            await refresh_entry(entry)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
