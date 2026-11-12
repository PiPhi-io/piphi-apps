from __future__ import annotations

import asyncio
import os
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
from .mqtt_client import PrinterMqttSession
from .report import normalize_print_report
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .simulator import SimulatedPrinterSession

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
_sessions: dict[str, PrinterMqttSession | SimulatedPrinterSession] = {}
_reports: dict[str, dict[str, Any]] = {}


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    # Never retain the access code or a model_dump of the submitted config in
    # the public registry; /state returns registry entries verbatim.
    return {
        **identity,
        "host": config.host,
        "serial_suffix": config.serial[-4:] if config.serial else None,
        "alias": config.alias or ("Simulated Bambu printer" if config.simulation_mode else None),
        "simulation_mode": config.simulation_mode,
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


def current_state(config_id: str) -> dict[str, Any]:
    return dict(registry.state_snapshots.get(config_id, {}).get("state", {}))


async def record_report(config_id: str, payload: dict[str, Any]) -> None:
    entry = registry.get(config_id)
    if entry is None:
        return
    result = normalize_print_report(payload, _reports.get(config_id))
    if result is None:
        return
    result["simulation_mode"] = bool(entry["simulation_mode"])
    _reports[config_id] = result
    registry.update_state(config_id, result, device_id=entry["device_id"])
    units = {
        "print_progress_percent": "%",
        "remaining_time_minutes": "min",
        "nozzle_temperature_c": "C",
        "target_nozzle_temperature_c": "C",
        "bed_temperature_c": "C",
        "target_bed_temperature_c": "C",
    }
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=entry["config_id"],
        device_id=entry["device_id"],
        container_id=entry.get("container_id"),
        metrics=result,
        units={key: unit for key, unit in units.items() if key in result},
    )


async def mark_offline(config_id: str) -> None:
    entry = registry.get(config_id)
    if entry is None:
        return
    _reports.pop(config_id, None)
    registry.update_state(
        config_id,
        {**current_state(config_id), "connected": False},
        device_id=entry["device_id"],
    )


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = entry["config_id"]
    loop = asyncio.get_running_loop()
    callbacks = dict(
        on_report=lambda payload: loop.call_soon_threadsafe(
            lambda: asyncio.create_task(record_report(config_id, payload))
            if _sessions.get(config_id) is session else None
        ),
        on_offline=lambda: loop.call_soon_threadsafe(
            lambda: asyncio.create_task(mark_offline(config_id))
            if _sessions.get(config_id) is session else None
        ),
    )
    if config.simulation_mode:
        session = SimulatedPrinterSession(**callbacks)
    else:
        assert config.host is not None and config.serial is not None and config.access_code is not None
        session = PrinterMqttSession(
            host=config.host,
            serial=config.serial,
            access_code=config.access_code.get_secret_value(),
            **callbacks,
        )
    # Construct TLS and open the nonblocking MQTT session before replacing a
    # previous config. Failed setup must not claim a connection.
    session.start()
    old_session = _sessions.pop(config_id, None)
    _reports.pop(config_id, None)
    _sessions[config_id] = session
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {"connected": False, "simulation_mode": config.simulation_mode},
        device_id=entry["device_id"],
    )
    append_runtime_event("runtime.config.applied", entry, {"host": config.host})
    if old_session is not None:
        old_session.stop()


async def remove_config(config_id: str) -> bool:
    _reports.pop(config_id, None)
    session = _sessions.pop(config_id, None)
    if session is not None:
        session.stop()
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event("runtime.config.removed", entry, {"host": entry.get("host")})
    return True


async def close_sessions() -> None:
    _reports.clear()
    sessions = list(_sessions.values())
    _sessions.clear()
    for session in sessions:
        session.stop()


def request_refresh(config_id: str) -> bool:
    session = _sessions.get(config_id)
    return session.request_full_status() if session is not None else False


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            config_id = str(request.config_id or target.get("config_id") or "")
            entry = get_entry_or_404(config_id)
            requested = request_refresh(config_id)
            return {
                "command": _command_name,
                "device_id": entry["device_id"],
                "config_id": config_id,
                "requested": requested,
                "reason": None if requested else "printer_offline_or_refresh_rate_limited",
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
