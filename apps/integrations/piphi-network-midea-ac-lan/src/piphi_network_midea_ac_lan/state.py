from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Awaitable, Callable

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
from .midea_client import MideaLanClient
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

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
_configs: dict[str, DeviceConfig] = {}
_clients: dict[str, MideaLanClient] = {}
_locks: dict[str, asyncio.Lock] = {}
_client_connector: Callable[..., Awaitable[MideaLanClient]] = MideaLanClient.connect


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"token", "key"}),
        "next_poll_at": 0.0,
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
    _configs[config_id] = config
    _clients.pop(config_id, None)
    _locks.setdefault(config_id, asyncio.Lock())
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {"connected": False},
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    _configs.pop(config_id, None)
    _clients.pop(config_id, None)
    _locks.pop(config_id, None)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


async def _client_for(config_id: str) -> MideaLanClient:
    cached = _clients.get(config_id)
    if cached is not None:
        return cached
    config = _configs.get(config_id)
    if config is None:
        raise ValueError("Midea configuration is unavailable")
    client = await _client_connector(
        host=config.host,
        port=config.port,
        device_id=config.midea_device_id,
        token=config.token,
        key=config.key,
    )
    _clients[config_id] = client
    return client


def _publish_state(entry: dict[str, Any], metrics: dict[str, Any]) -> None:
    config_id = entry["config_id"]
    previous = registry.state_snapshots.get(config_id, {}).get("state", {})
    latest = {**previous, **metrics}
    registry.update_state(config_id, latest, device_id=entry["device_id"])
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=entry["device_id"],
        container_id=entry.get("container_id"),
        metrics=latest,
        units={
            "target_temperature_c": "°C",
            "indoor_temperature_c": "°C",
            "outdoor_temperature_c": "°C",
            "fan_speed_percent": "%",
        },
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: (
                completed.exception() if not completed.cancelled() else None
            )
        )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = entry["config_id"]
    async with _locks.setdefault(config_id, asyncio.Lock()):
        try:
            metrics = await (await _client_for(config_id)).refresh()
        except Exception as exc:
            _clients.pop(config_id, None)
            logger.warning(
                "midea_refresh_failed config_id=%s error=%s",
                config_id,
                type(exc).__name__,
            )
            metrics = {"connected": False}
        _publish_state(entry, metrics)
        config = _configs.get(config_id)
        entry["next_poll_at"] = time.monotonic() + max(
            5, config.poll_interval_seconds if config else 30
        )
        return metrics


async def execute_command(
    entry: dict[str, Any], command: str, args: dict[str, Any]
) -> dict[str, Any]:
    if command == "refresh":
        return await refresh_entry(entry)
    config_id = entry["config_id"]
    config = _configs.get(config_id)
    if config is None or not config.controls_enabled:
        raise ValueError("Midea controls are disabled for this configuration")
    async with _locks.setdefault(config_id, asyncio.Lock()):
        metrics = await (await _client_for(config_id)).execute(command, args)
        _publish_state(entry, metrics)
        return metrics


async def poll_devices() -> None:
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if entry is None or entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 30
            await refresh_entry(entry)


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
                raise ValueError("Unknown configured Midea air conditioner")
            metrics = await execute_command(entry, _command_name, request.args)
            if not metrics.get("connected"):
                raise RuntimeError("Midea air conditioner is unavailable")
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
                "state": metrics,
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
