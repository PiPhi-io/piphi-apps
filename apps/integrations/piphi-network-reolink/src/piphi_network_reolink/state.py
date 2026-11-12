from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
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
from .reolink_client import ReolinkClient
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
_clients: dict[str, ReolinkClient] = {}
_locks: dict[str, asyncio.Lock] = {}
_client_connector: Callable[..., Awaitable[ReolinkClient]] = ReolinkClient.connect


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(
            exclude={"password"},
            mode="json",
        ),
        "channels": [],
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


async def _discard_client(config_id: str) -> None:
    client = _clients.pop(config_id, None)
    if client is not None:
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 - cleanup must not block reconfiguration
            logger.debug(
                "reolink_client_close_failed config_id=%s error=%s", config_id, type(exc).__name__
            )


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = str(entry["config_id"])
    await _discard_client(config_id)
    _configs[config_id] = config
    _locks.setdefault(config_id, asyncio.Lock())
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {"connected": False, "camera_count": 0},
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    _configs.pop(config_id, None)
    _locks.pop(config_id, None)
    await _discard_client(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


async def _client_for(config_id: str) -> ReolinkClient:
    cached = _clients.get(config_id)
    if cached is not None:
        return cached
    config = _configs.get(config_id)
    if config is None:
        raise ValueError("Reolink configuration is unavailable")
    client = await _client_connector(
        host=config.host,
        username=config.username,
        password=config.password.get_secret_value(),
        port=config.port,
        use_https=config.use_https,
    )
    _clients[config_id] = client
    return client


def _publish_state(entry: dict[str, Any], snapshot: dict[str, Any]) -> None:
    config_id = str(entry["config_id"])
    entry["channels"] = list(snapshot.get("channels") or [])
    entry["device_name"] = snapshot.get("name")
    entry["model"] = snapshot.get("model")
    entry["is_nvr"] = bool(snapshot.get("is_nvr"))
    state = {
        "connected": bool(snapshot.get("connected")),
        "camera_count": int(snapshot.get("camera_count") or 0),
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=state,
        units={"camera_count": "cameras"},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with _locks.setdefault(config_id, asyncio.Lock()):
        try:
            snapshot = await (await _client_for(config_id)).refresh()
        except Exception as exc:  # noqa: BLE001 - upstream exposes a broad error surface
            await _discard_client(config_id)
            logger.warning(
                "reolink_refresh_failed config_id=%s error=%s",
                config_id,
                type(exc).__name__,
            )
            snapshot = {"connected": False, "camera_count": 0, "channels": []}
        _publish_state(entry, snapshot)
        config = _configs.get(config_id)
        entry["next_poll_at"] = time.monotonic() + (config.poll_interval_seconds if config else 30)
        return snapshot


async def poll_devices() -> None:
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if entry is None or float(entry.get("next_poll_at", 0)) > now:
                continue
            entry["next_poll_at"] = now + 30
            await refresh_entry(entry)


async def close_clients() -> None:
    for config_id in list(_clients):
        await _discard_client(config_id)


def _register_automation_actions() -> None:
    async def refresh_handler(request):
        target = request.target if isinstance(request.target, dict) else {}
        device_id = str(request.device_id or target.get("device_id") or "")
        config_id = str(request.config_id or target.get("config_id") or device_id)
        entry = registry.get(config_id)
        if entry is None:
            raise ValueError("Unknown configured Reolink camera or NVR")
        snapshot = await refresh_entry(entry)
        if not snapshot.get("connected"):
            raise RuntimeError("Reolink camera or NVR is unavailable")
        event = append_runtime_event(
            "runtime.command.received",
            entry,
            {"command": "refresh", "device_id": device_id, "target": target},
        )
        return {
            "event": event,
            "command": "refresh",
            "device_id": device_id,
            "config_id": config_id,
            "state": {
                "connected": True,
                "camera_count": snapshot["camera_count"],
            },
        }

    automations.action("refresh", label=COMMANDS["refresh"]["description"])(refresh_handler)


_register_automation_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        entry = registry.get(config_id)
        if entry is not None:
            await refresh_entry(entry)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
