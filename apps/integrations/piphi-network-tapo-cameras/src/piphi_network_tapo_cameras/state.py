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
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .tapo_client import TapoClient, TapoSetupError

logger = logging.getLogger(__name__)
MASKED_SECRETS = {"********", "••••••••"}

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
class TapoRuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    clients: dict[str, TapoClient] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connector: Callable[..., Awaitable[TapoClient]] = TapoClient.connect


runtime_data = TapoRuntimeData()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def append_runtime_event(
    event_type: str, device: dict[str, Any], payload: dict[str, Any] | None = None
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
        raise HTTPException(status_code=404, detail={"error": "unknown_configuration"})
    return entry


def _resolved_config(config: DeviceConfig) -> DeviceConfig:
    config_id = str(config.config_id or config.id)
    if config.password.get_secret_value() not in MASKED_SECRETS:
        return config
    previous = runtime_data.configs.get(config_id)
    if previous is None or previous.host != config.host or previous.username != config.username:
        raise HTTPException(status_code=422, detail={"error": "password_required"})
    return config.model_copy(update={"password": previous.password})


def _make_entry(config: DeviceConfig, snapshot: dict[str, Any]) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "device_id": f"{INTEGRATION_ID}:{snapshot['hardware_id']}",
        "hardware_id": snapshot["hardware_id"],
        "alias": config.alias,
        "config": {
            "id": config.id,
            "config_id": str(config.config_id or config.id),
            "container_id": config.container_id,
            "alias": config.alias,
            "poll_interval_seconds": config.poll_interval_seconds,
        },
        "next_poll_at": time.monotonic() + config.poll_interval_seconds,
        "consecutive_failures": 0,
        "availability": "online",
        "last_success_at": _now(),
        "last_error_category": None,
    }


async def _close_client(client: TapoClient, config_id: str) -> None:
    try:
        await client.close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not hide the primary outcome
        logger.debug("tapo_close_failed config_id=%s error=%s", config_id, type(exc).__name__)


async def _discard_client(config_id: str) -> None:
    client = runtime_data.clients.pop(config_id, None)
    if client is not None:
        await _close_client(client, config_id)


async def apply_config(config: DeviceConfig) -> None:
    config = _resolved_config(config)
    config_id = str(config.config_id or config.id)
    candidate: TapoClient | None = None
    try:
        candidate = await runtime_data.connector(
            host=config.host,
            username=config.username,
            password=config.password.get_secret_value(),
        )
        snapshot = await candidate.refresh()
    except TapoSetupError as exc:
        if candidate is not None:
            await _close_client(candidate, config_id)
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    except Exception as exc:
        if candidate is not None:
            await _close_client(candidate, config_id)
        logger.warning("tapo_setup_failed config_id=%s error=%s", config_id, type(exc).__name__)
        raise HTTPException(status_code=422, detail={"error": "unreachable"}) from exc

    entry = _make_entry(config, snapshot)
    old_client: TapoClient | None = None
    try:
        async with runtime_data.config_lock:
            duplicate = next(
                (
                    item
                    for other_id, item in registry.entries.items()
                    if other_id != config_id and item.get("hardware_id") == snapshot["hardware_id"]
                ),
                None,
            )
            if duplicate is not None:
                raise HTTPException(status_code=409, detail={"error": "device_already_configured"})
            previous = registry.get(config_id)
            if previous is not None and previous.get("hardware_id") != snapshot["hardware_id"]:
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
    append_runtime_event("runtime.config.applied", entry, {"reconfigured": old_client is not None})


async def remove_config(config_id: str) -> bool:
    async with runtime_data.config_lock:
        lock = runtime_data.locks.setdefault(config_id, asyncio.Lock())
        async with lock:
            runtime_data.configs.pop(config_id, None)
            await _discard_client(config_id)
            entry = registry.remove(config_id)
        runtime_data.locks.pop(config_id, None)
    if entry is None:
        return False
    append_runtime_event("runtime.config.removed", entry)
    return True


def _publish_state(entry: dict[str, Any], snapshot: dict[str, Any]) -> None:
    config_id = str(entry["config_id"])
    for key in ("name", "model", "hardware", "firmware", "device_type", "privacy_mode", "signal_strength"):
        entry[key] = snapshot.get(key)
    entry.update(
        availability="online",
        last_success_at=_now(),
        last_error_category=None,
        consecutive_failures=0,
    )
    privacy_mode = snapshot.get("privacy_mode")
    state = {
        "connected": True,
        "available": True,
        "stale": False,
        "privacy_mode": privacy_mode,
        "camera_enabled": None if privacy_mode is None else not privacy_mode,
        "signal_strength": snapshot.get("signal_strength"),
        "last_success_at": entry["last_success_at"],
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=state,
        units={"signal_strength": "dBm"},
    )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        if registry.get(config_id) is not entry:
            return {"connected": False, "available": False, "stale": True}
        client = runtime_data.clients.get(config_id)
        config = runtime_data.configs.get(config_id)
        try:
            if client is None:
                if config is None:
                    raise TapoSetupError("configuration_unavailable")
                client = await runtime_data.connector(
                    host=config.host,
                    username=config.username,
                    password=config.password.get_secret_value(),
                )
                runtime_data.clients[config_id] = client
            snapshot = await client.refresh()
            if snapshot.get("hardware_id") != entry.get("hardware_id"):
                raise TapoSetupError("device_identity_mismatch")
        except Exception as exc:  # noqa: BLE001 - upstream transport has broad failures
            await _discard_client(config_id)
            code = exc.code if isinstance(exc, TapoSetupError) else "unavailable"
            was_online = entry.get("availability") == "online"
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["last_error_category"] = code
            entry["availability"] = "reauth_required" if code == "invalid_auth" else "unavailable"
            prior = registry.state_snapshots.get(config_id, {}).get("state", {})
            state = {
                **{k: prior.get(k) for k in ("privacy_mode", "camera_enabled", "signal_strength", "last_success_at")},
                "connected": False,
                "available": False,
                "stale": True,
                "error_category": code,
            }
            registry.update_state(config_id, state, device_id=entry["device_id"])
            if was_online:
                append_runtime_event("device.unavailable", entry, {"category": code})
            snapshot = state
        else:
            was_offline = entry.get("availability") != "online"
            _publish_state(entry, snapshot)
            if was_offline:
                append_runtime_event("device.restored", entry)
        interval = config.poll_interval_seconds if config else 60
        failures = int(entry.get("consecutive_failures", 0))
        permanent_failure = entry.get("availability") == "reauth_required"
        entry["next_poll_at"] = (
            float("inf")
            if permanent_failure
            else time.monotonic() + min(3600, interval * (2 ** min(failures, 5)))
        )
        return snapshot


async def poll_devices() -> None:
    while True:
        await asyncio.sleep(2)
        now = time.monotonic()
        due = [
            entry
            for config_id in registry.ids()
            if (entry := registry.get(config_id)) is not None
            and float(entry.get("next_poll_at", 0)) <= now
        ]
        if due:
            await asyncio.gather(*(refresh_entry(entry) for entry in due), return_exceptions=True)


async def close_clients() -> None:
    for config_id in list(runtime_data.clients):
        await _discard_client(config_id)


def _register_automation_actions() -> None:
    async def refresh_handler(request):
        target = request.target if isinstance(request.target, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        entry = registry.get(config_id)
        if entry is None:
            raise ValueError("Unknown configured Tapo camera")
        snapshot = await refresh_entry(entry)
        if not snapshot.get("connected"):
            raise RuntimeError("Tapo camera is unavailable")
        return {"command": "refresh", "config_id": config_id, "state": snapshot}

    automations.action("refresh", label=COMMANDS["refresh"]["description"])(refresh_handler)


_register_automation_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        if (entry := registry.get(config_id)) is not None:
            await refresh_entry(entry)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
