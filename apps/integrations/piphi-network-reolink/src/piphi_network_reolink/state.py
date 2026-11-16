from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
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
from .reolink_client import ReolinkClient, ReolinkSetupError
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


@dataclass(slots=True)
class ReolinkRuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    clients: dict[str, ReolinkClient] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client_connector: Callable[..., Awaitable[ReolinkClient]] = ReolinkClient.connect


runtime_data = ReolinkRuntimeData()


def make_entry(config: DeviceConfig, snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    hardware_id = str(snapshot["hardware_id"])
    return {
        **identity,
        "device_id": f"{INTEGRATION_ID}:{hardware_id}",
        "hardware_id": hardware_id,
        "alias": config.alias,
        "config": config.model_dump(
            exclude={"password"},
            mode="json",
        ),
        "channels": list(snapshot.get("channels") or []),
        "next_poll_at": time.monotonic(),
        "consecutive_failures": 0,
        "last_success_at": datetime.now(UTC).isoformat(),
        "last_error_category": None,
        "availability": "online",
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
    client = runtime_data.clients.pop(config_id, None)
    if client is not None:
        await _close_client(client, config_id)


async def _close_client(client: ReolinkClient, config_id: str) -> None:
    try:
        await client.close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not mask the primary outcome
        logger.debug(
            "reolink_client_close_failed config_id=%s error=%s", config_id, type(exc).__name__
        )


async def apply_config(config: DeviceConfig) -> None:
    config_id = str(config.config_id or config.id)
    try:
        candidate = await runtime_data.client_connector(
            host=config.host,
            username=config.username,
            password=config.password.get_secret_value(),
            port=config.port,
            use_https=config.use_https,
        )
        snapshot = await candidate.refresh()
    except ReolinkSetupError as exc:
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    except Exception as exc:
        logger.warning("reolink_setup_failed config_id=%s error=%s", config_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail={"error": "cannot_connect"}) from exc

    hardware_id = snapshot.get("hardware_id")
    if not hardware_id:
        await _close_client(candidate, config_id)
        raise HTTPException(status_code=422, detail={"error": "stable_identity_unavailable"})
    entry = make_entry(config, snapshot)
    old_client: ReolinkClient | None = None
    try:
        async with runtime_data.config_lock:
            duplicate = next(
                (
                    item
                    for other_id, item in registry.entries.items()
                    if other_id != config_id and item.get("hardware_id") == hardware_id
                ),
                None,
            )
            if duplicate is not None:
                raise HTTPException(status_code=409, detail={"error": "device_already_configured"})
            previous = registry.get(config_id)
            if previous is not None and previous.get("hardware_id") != hardware_id:
                raise HTTPException(status_code=409, detail={"error": "device_identity_mismatch"})
            old_client = runtime_data.clients.get(config_id)
            runtime_data.configs[config_id] = config
            runtime_data.clients[config_id] = candidate
            runtime_data.locks.setdefault(config_id, asyncio.Lock())
            registry.set(config_id, entry)
            _publish_state(entry, snapshot)
    except Exception:
        await _close_client(candidate, config_id)
        raise
    if old_client is not None and old_client is not candidate:
        await _close_client(old_client, config_id)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"device_id": entry["device_id"], "reconfigured": old_client is not None},
    )


async def remove_config(config_id: str) -> bool:
    runtime_data.configs.pop(config_id, None)
    runtime_data.locks.pop(config_id, None)
    await _discard_client(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"device_id": entry.get("device_id")},
    )
    return True


async def _client_for(config_id: str) -> ReolinkClient:
    cached = runtime_data.clients.get(config_id)
    if cached is not None:
        return cached
    config = runtime_data.configs.get(config_id)
    if config is None:
        raise ValueError("Reolink configuration is unavailable")
    client = await runtime_data.client_connector(
        host=config.host,
        username=config.username,
        password=config.password.get_secret_value(),
        port=config.port,
        use_https=config.use_https,
    )
    runtime_data.clients[config_id] = client
    return client


def _publish_state(entry: dict[str, Any], snapshot: dict[str, Any]) -> None:
    config_id = str(entry["config_id"])
    entry["channels"] = list(snapshot.get("channels") or [])
    entry["device_name"] = snapshot.get("name")
    entry["model"] = snapshot.get("model")
    entry["hardware"] = snapshot.get("hardware")
    entry["firmware"] = snapshot.get("firmware")
    entry["is_nvr"] = bool(snapshot.get("is_nvr"))
    entry["is_battery"] = bool(snapshot.get("is_battery"))
    entry["availability"] = "online"
    entry["last_success_at"] = datetime.now(UTC).isoformat()
    entry["last_error_category"] = None
    entry["consecutive_failures"] = 0
    state = {
        "connected": bool(snapshot.get("connected")),
        "camera_count": int(snapshot.get("camera_count") or 0),
        "stale": False,
        "channels": {
            str(channel.get("hardware_id") or channel["channel"]): {
                "connected": bool(channel.get("online")),
                "sleeping": bool(channel.get("sleeping")),
            }
            for channel in entry["channels"]
        },
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
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        try:
            snapshot = await (await _client_for(config_id)).refresh()
        except Exception as exc:  # noqa: BLE001 - upstream exposes a broad error surface
            await _discard_client(config_id)
            logger.warning(
                "reolink_refresh_failed config_id=%s error=%s",
                config_id,
                type(exc).__name__,
            )
            failures = int(entry.get("consecutive_failures", 0)) + 1
            was_online = entry.get("availability") == "online"
            entry["consecutive_failures"] = failures
            entry["last_error_category"] = (
                exc.code if isinstance(exc, ReolinkSetupError) else "unavailable"
            )
            requires_reauth = isinstance(exc, ReolinkSetupError) and exc.code == "invalid_auth"
            entry["availability"] = "reauth_required" if requires_reauth else "unavailable"
            state = {
                "connected": False,
                "camera_count": len(entry.get("channels", [])),
                "stale": True,
                "channels": {
                    str(channel.get("hardware_id") or channel["channel"]): {
                        "connected": False,
                        "sleeping": bool(channel.get("sleeping")),
                    }
                    for channel in entry.get("channels", [])
                },
            }
            registry.update_state(config_id, state, device_id=entry["device_id"])
            if was_online:
                append_runtime_event(
                    "device.unavailable",
                    entry,
                    {"category": entry["last_error_category"]},
                )
            snapshot = {**state, "channels": list(entry.get("channels", []))}
        else:
            if snapshot.get("hardware_id") != entry.get("hardware_id"):
                await _discard_client(config_id)
                raise HTTPException(status_code=409, detail={"error": "device_identity_mismatch"})
            was_offline = entry.get("availability") != "online"
            _publish_state(entry, snapshot)
            if was_offline:
                append_runtime_event("device.restored", entry)
        config = runtime_data.configs.get(config_id)
        interval = config.poll_interval_seconds if config else 60
        if entry.get("is_battery") or any(c.get("sleeping") for c in entry.get("channels", [])):
            interval = max(interval, 900)
        failures = int(entry.get("consecutive_failures", 0))
        interval = min(900, interval * (2 ** min(failures, 4)))
        entry["next_poll_at"] = time.monotonic() + interval
        return snapshot


async def poll_devices() -> None:
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        due: list[dict[str, Any]] = []
        for config_id in registry.ids():
            entry = registry.get(config_id)
            if entry is None or float(entry.get("next_poll_at", 0)) > now:
                continue
            entry["next_poll_at"] = now + 30
            due.append(entry)
        if due:
            await asyncio.gather(*(refresh_entry(entry) for entry in due), return_exceptions=True)


async def close_clients() -> None:
    for config_id in list(runtime_data.clients):
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
