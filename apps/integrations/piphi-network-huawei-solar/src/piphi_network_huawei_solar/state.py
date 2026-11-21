from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
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
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .sun2000 import read_sun2000

logger = logging.getLogger(__name__)

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
refresh_locks: dict[str, asyncio.Lock] = {}


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    config_id = str(config.config_id or config.id)
    return {
        **identity,
        "config_id": config_id,
        "host": config.host,
        "alias": config.alias,
        "source_identity": f"{config.host}/unit/{config.unit_id}",
        "config": config.model_dump(),
        "consecutive_failures": 0,
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
            "available": False,
            "stale": True,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    await refresh_entry(entry)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"alias": config.alias},
    )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with refresh_locks.setdefault(config_id, asyncio.Lock()):
        config = DeviceConfig.model_validate(entry["config"])
        previous_status = str(entry.get("status") or "initializing")
        try:
            reading = await read_sun2000(config.host, config.unit_id)
        except (OSError, ValueError, EOFError, TimeoutError) as exc:
            logger.warning(
                "sun2000_read_failed config_id=%s error=%s",
                config_id,
                type(exc).__name__,
            )
            failures = int(entry.get("consecutive_failures") or 0) + 1
            entry["consecutive_failures"] = failures
            entry["status"] = "unavailable"
            entry["next_poll_at"] = time.monotonic() + min(900, 60 * (2 ** min(failures - 1, 4)))
            state = {
                **dict(entry.get("last_good") or {}),
                "connected": False,
                "available": False,
                "stale": bool(entry.get("last_good")),
                "reason": "inverter_read_failed",
                "consecutive_failures": failures,
            }
            registry.update_state(config_id, state, device_id=entry["device_id"])
            if previous_status not in {"initializing", "unavailable"}:
                append_runtime_event("inverter.unavailable", entry, {"reason": state["reason"]})
            return state
        now = datetime.now(UTC).isoformat()
        metrics = {
            "connected": True,
            "available": True,
            "stale": False,
            "active_power_w": reading.active_power_w,
            "daily_yield_kwh": reading.daily_yield_kwh,
            "last_success_at": now,
            "consecutive_failures": 0,
        }
        entry["last_good"] = metrics.copy()
        entry["consecutive_failures"] = 0
        entry["status"] = "available"
        entry["next_poll_at"] = time.monotonic() + config.poll_interval_seconds
        registry.update_state(config_id, metrics, device_id=entry["device_id"])
        if previous_status == "unavailable":
            append_runtime_event("inverter.recovered", entry)
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={"active_power_w": "W", "daily_yield_kwh": "kWh"},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )
    return metrics


async def poll_inverters() -> None:
    while True:
        await asyncio.sleep(5)
        now = time.monotonic()
        for entry in list(registry.entries.values()):
            if entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 300
            await refresh_entry(entry)


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    refresh_locks.pop(config_id, None)
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"alias": entry.get("alias")},
    )
    return True


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "demo-device")
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id)
            if entry is None:
                raise ValueError("Unknown configured inverter")
            metrics = await refresh_entry(entry)
            if not metrics.get("connected"):
                raise RuntimeError("Huawei inverter is unavailable")
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
                "active_power_w": metrics["active_power_w"],
                "daily_yield_kwh": metrics["daily_yield_kwh"],
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
