from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
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
        Path(os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3"))
    )
)

capabilities = CAPABILITIES
commands = COMMANDS
MASKED_SECRETS = {"********", "••••••••"}
_sessions: dict[str, PrinterMqttSession | SimulatedPrinterSession] = {}
_reports: dict[str, dict[str, Any]] = {}


@dataclass(slots=True)
class BambuRuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


runtime_data = BambuRuntimeData()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _device_id(config: DeviceConfig) -> str:
    identity = "simulation" if config.simulation_mode else str(config.serial)
    digest = sha256(f"{INTEGRATION_ID}:{identity}".encode()).hexdigest()[:20]
    return f"{INTEGRATION_ID}:{digest}"


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    # Never retain the access code or a model_dump of the submitted config in
    # the public registry; /state returns registry entries verbatim.
    return {
        **identity,
        "device_id": _device_id(config),
        "serial_suffix": config.serial[-4:] if config.serial else None,
        "model": config.model or "Simulator",
        "alias": config.alias or ("Simulated Bambu printer" if config.simulation_mode else None),
        "simulation_mode": config.simulation_mode,
        "availability": "connecting",
        "consecutive_failures": 0,
        "last_error_category": None,
        "last_success_at": None,
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
    was_unavailable = entry.get("availability") in {"unavailable", "reauth_required"}
    entry.update(
        availability="online",
        consecutive_failures=0,
        last_error_category=None,
        last_success_at=_now(),
    )
    result.update(
        available=True,
        stale=False,
        last_report_at=entry["last_success_at"],
        consecutive_failures=0,
    )
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
    if was_unavailable:
        append_runtime_event("device.restored", entry)


async def mark_offline(config_id: str, category: str | None = None) -> None:
    entry = registry.get(config_id)
    if entry is None:
        return
    was_online = entry.get("availability") == "online"
    category = category or runtime_data.failures.pop(config_id, "transport_lost")
    failures = int(entry.get("consecutive_failures", 0)) + 1
    entry.update(
        availability="reauth_required" if category == "invalid_auth" else "unavailable",
        consecutive_failures=failures,
        last_error_category=category,
    )
    registry.update_state(
        config_id,
        {
            **current_state(config_id),
            "connected": False,
            "available": False,
            "stale": True,
            "error_category": category,
            "consecutive_failures": failures,
        },
        device_id=entry["device_id"],
    )
    if was_online:
        append_runtime_event("device.unavailable", entry, {"category": category})


def _remember_failure(config_id: str, category: str) -> None:
    runtime_data.failures[config_id] = category


async def apply_config(config: DeviceConfig) -> None:
    config_id_hint = str(config.config_id or config.id)
    if config.access_code is not None and config.access_code.get_secret_value() in MASKED_SECRETS:
        previous = runtime_data.configs.get(config_id_hint)
        if previous is None or previous.access_code is None:
            raise HTTPException(status_code=422, detail={"error": "credentials_required"})
        config = config.model_copy(update={"access_code": previous.access_code})
    entry = make_entry(config)
    config_id = entry["config_id"]
    loop = asyncio.get_running_loop()

    session: PrinterMqttSession | SimulatedPrinterSession

    def on_report(payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(record_report(config_id, payload))
            if _sessions.get(config_id) is session else None
        )

    def on_offline() -> None:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(mark_offline(config_id))
            if _sessions.get(config_id) is session else None
        )

    def on_failure(category: str) -> None:
        loop.call_soon_threadsafe(_remember_failure, config_id, category)

    if config.simulation_mode:
        session = SimulatedPrinterSession(
            on_report=on_report, on_offline=on_offline, on_failure=on_failure
        )
    else:
        if config.host is None or config.serial is None or config.access_code is None:
            raise ValueError("validated real printer configuration is incomplete")
        session = PrinterMqttSession(
            host=config.host,
            serial=config.serial,
            access_code=config.access_code.get_secret_value(),
            on_report=on_report,
            on_offline=on_offline,
            on_failure=on_failure,
        )
    try:
        session.start()
        await session.wait_ready()
    except Exception:
        session.stop()
        raise
    old_session = None
    async with runtime_data.config_lock:
        lock = runtime_data.locks.setdefault(config_id, asyncio.Lock())
        async with lock:
            duplicate = next(
                (
                    item
                    for other_id, item in registry.entries.items()
                    if other_id != config_id and item.get("device_id") == entry["device_id"]
                ),
                None,
            )
            previous_entry = registry.get(config_id)
            if duplicate is not None:
                session.stop()
                raise HTTPException(status_code=409, detail={"error": "device_already_configured"})
            if previous_entry is not None and previous_entry.get("device_id") != entry["device_id"]:
                session.stop()
                raise HTTPException(status_code=409, detail={"error": "device_identity_mismatch"})
            previous_config = runtime_data.configs.get(config_id)
            previous_state = registry.state_snapshots.get(config_id)
            old_session = _sessions.get(config_id)
            try:
                runtime_data.configs[config_id] = config
                _sessions[config_id] = session
                _reports.pop(config_id, None)
                registry.set(config_id, entry)
                registry.update_state(
                    config_id,
                    {
                        "connected": False,
                        "available": False,
                        "stale": True,
                        "simulation_mode": config.simulation_mode,
                        "consecutive_failures": 0,
                    },
                    device_id=entry["device_id"],
                )
            except Exception:
                if previous_config is None:
                    runtime_data.configs.pop(config_id, None)
                else:
                    runtime_data.configs[config_id] = previous_config
                if old_session is None:
                    _sessions.pop(config_id, None)
                else:
                    _sessions[config_id] = old_session
                if previous_entry is None:
                    registry.entries.pop(config_id, None)
                else:
                    registry.entries[config_id] = previous_entry
                if previous_state is None:
                    registry.state_snapshots.pop(config_id, None)
                else:
                    registry.state_snapshots[config_id] = previous_state
                session.stop()
                raise
    append_runtime_event(
        "runtime.config.applied", entry, {"reconfigured": old_session is not None}
    )
    if old_session is not None:
        old_session.stop()


async def remove_config(config_id: str) -> bool:
    async with runtime_data.config_lock:
        lock = runtime_data.locks.setdefault(config_id, asyncio.Lock())
        async with lock:
            _reports.pop(config_id, None)
            runtime_data.configs.pop(config_id, None)
            runtime_data.failures.pop(config_id, None)
            session = _sessions.pop(config_id, None)
            if session is not None:
                session.stop()
            entry = registry.remove(config_id)
        runtime_data.locks.pop(config_id, None)
    if entry is None:
        return False
    append_runtime_event("runtime.config.removed", entry)
    return True


async def close_sessions() -> None:
    _reports.clear()
    sessions = list(_sessions.values())
    _sessions.clear()
    runtime_data.failures.clear()
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
            requested_device_id = str(
                getattr(request, "device_id", None) or target.get("device_id") or ""
            ).strip()
            if requested_device_id and requested_device_id != str(entry["device_id"]):
                raise ValueError("Printer target does not match the configured device")
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
