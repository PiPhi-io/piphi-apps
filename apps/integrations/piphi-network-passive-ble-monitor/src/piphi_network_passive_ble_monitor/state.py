from __future__ import annotations

import asyncio
import logging
import os
from time import monotonic
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
from .scanner import SensorAdvertisement, scan_bthome
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
logger = logging.getLogger(__name__)
_scan_lock = asyncio.Lock()
_last_seen: dict[str, float] = {}
_trigger_based: set[str] = set()


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "poll_interval_seconds": config.poll_interval_seconds,
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
    config_id = entry["config_id"]
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {
            "connected": False,
        },
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    _last_seen.pop(config_id, None)
    _trigger_based.discard(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


def _publish_state(entry: dict[str, Any], metrics: dict[str, Any]) -> None:
    config_id = entry["config_id"]
    previous = registry.state_snapshots.get(config_id, {}).get("state", {})
    latest = {**previous, **metrics}
    registry.update_state(config_id, latest, device_id=entry["device_id"])
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=entry["device_id"],
        container_id=entry.get("container_id"),
        metrics={key: value for key, value in latest.items() if key != "trigger_based"},
        units={
            "battery_percent": "%",
            "temperature_c": "°C",
            "humidity_percent": "%",
            "rssi_dbm": "dBm",
        },
    )


def process_observations(observations: list[SensorAdvertisement], *, now: float | None = None) -> None:
    """Apply only advertisements for explicitly configured addresses."""
    seen_at = monotonic() if now is None else now
    by_address = {item.address.upper(): item for item in observations}
    for config_id in registry.ids():
        entry = registry.get(config_id)
        if entry is None:
            continue
        observation = by_address.get(entry["host"])
        if observation is not None:
            _last_seen[config_id] = seen_at
            if observation.metrics["trigger_based"]:
                _trigger_based.add(config_id)
            else:
                _trigger_based.discard(config_id)
            metrics = {**observation.metrics, "connected": True}
            if observation.rssi is not None and -127 <= observation.rssi <= 20:
                metrics["rssi_dbm"] = observation.rssi
            _publish_state(entry, metrics)
        elif (
            config_id not in _trigger_based
            and config_id in _last_seen
            and seen_at - _last_seen[config_id] > entry["poll_interval_seconds"] * 3
        ):
            previous = registry.state_snapshots.get(config_id, {}).get("state", {})
            if previous.get("connected"):
                _publish_state(entry, {"connected": False})


async def scan_once() -> list[SensorAdvertisement]:
    """Run one bounded BLE scan, serialized across polling and manual refresh."""
    async with _scan_lock:
        observations = await scan_bthome(timeout=5.0)
        process_observations(observations)
        return observations


async def refresh_config(config_id: str) -> dict[str, Any]:
    get_entry_or_404(config_id)
    await scan_once()
    return registry.state_snapshots.get(config_id, {}).get("state", {})


async def scan_poll_loop() -> None:
    while True:
        if registry.ids():
            try:
                await scan_once()
            except Exception:
                logger.exception("BLE scan failed")
                for config_id in registry.ids():
                    entry = registry.get(config_id)
                    if entry is not None:
                        previous = registry.state_snapshots.get(config_id, {}).get("state", {})
                        if previous.get("connected"):
                            _publish_state(entry, {"connected": False})
        intervals = [
            entry["poll_interval_seconds"]
            for config_id in registry.ids()
            if (entry := registry.get(config_id)) is not None
        ]
        await asyncio.sleep(min(intervals, default=30))


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "demo-device")
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id) or {
                "device_id": device_id,
                "config_id": config_id,
            }
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
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await refresh_config(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
