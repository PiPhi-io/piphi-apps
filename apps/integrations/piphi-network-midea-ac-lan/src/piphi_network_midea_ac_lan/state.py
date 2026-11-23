from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from pydantic import SecretStr

from .contract import CAPABILITIES, COMMANDS
from .midea_client import MideaLanClient, MideaSetupError
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

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
_automation_ledger_path = Path(
    os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")
)
_automation_ledger_path.parent.mkdir(parents=True, exist_ok=True)
automations = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(_automation_ledger_path)
)

capabilities = CAPABILITIES
commands = COMMANDS


@dataclass(slots=True)
class MideaRuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    clients: dict[str, MideaLanClient] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connector: Callable[..., Awaitable[MideaLanClient]] = MideaLanClient.connect


runtime_data = MideaRuntimeData()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _secret_value(value: SecretStr | None) -> str | None:
    if value is None:
        return None
    return value.get_secret_value() or None


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


def _resolved_config(config: DeviceConfig) -> DeviceConfig:
    config_id = str(config.config_id or config.id)
    token = _secret_value(config.token)
    key = _secret_value(config.key)
    if token not in MASKED_SECRETS and key not in MASKED_SECRETS:
        return config
    if token not in MASKED_SECRETS or key not in MASKED_SECRETS:
        raise HTTPException(status_code=422, detail={"error": "credentials_required"})
    previous = runtime_data.configs.get(config_id)
    if previous is None or previous.token is None or previous.key is None:
        raise HTTPException(status_code=422, detail={"error": "credentials_required"})
    return config.model_copy(update={"token": previous.token, "key": previous.key})


def _make_entry(
    config: DeviceConfig,
    client: MideaLanClient,
) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    config_id = str(identity["config_id"])
    return {
        **identity,
        "device_id": f"{INTEGRATION_ID}:{client.hardware_id}",
        "hardware_id": client.hardware_id,
        "alias": config.alias,
        "config": {
            "id": config.id,
            "config_id": config_id,
            "container_id": config.container_id,
            "alias": config.alias,
            "poll_interval_seconds": config.poll_interval_seconds,
            "controls_enabled": config.controls_enabled,
            "address_configured": True,
            "credentials_configured": bool(config.token and config.key),
        },
        "next_poll_at": time.monotonic() + config.poll_interval_seconds,
        "consecutive_failures": 0,
        "availability": "online",
        "last_success_at": _now(),
        "last_error_category": None,
    }


async def _close_client(client: MideaLanClient, config_id: str) -> None:
    try:
        await client.close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not hide the primary result
        logger.debug(
            "midea_close_failed config_id=%s error=%s",
            config_id,
            type(exc).__name__,
        )


async def _discard_client(config_id: str) -> None:
    client = runtime_data.clients.pop(config_id, None)
    if client is not None:
        await _close_client(client, config_id)


def _publish_telemetry(entry: dict[str, Any], metrics: dict[str, Any]) -> None:
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={
            "target_temperature_c": "°C",
            "indoor_temperature_c": "°C",
            "outdoor_temperature_c": "°C",
            "fan_speed_percent": "%",
        },
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )


def _publish_state(entry: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    entry.update(
        availability="online",
        last_success_at=_now(),
        last_error_category=None,
        consecutive_failures=0,
    )
    state = {
        **snapshot,
        "connected": True,
        "available": True,
        "stale": False,
        "last_success_at": entry["last_success_at"],
        "consecutive_failures": 0,
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    _publish_telemetry(entry, state)
    return state


def _error_category(exc: Exception) -> str:
    if isinstance(exc, MideaSetupError):
        return exc.code
    return "invalid_auth" if "auth" in type(exc).__name__.lower() else "unavailable"


def _publish_unavailable(
    entry: dict[str, Any],
    category: str,
) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    was_online = entry.get("availability") == "online"
    failures = int(entry.get("consecutive_failures", 0)) + 1
    entry.update(
        availability="reauth_required" if category == "invalid_auth" else "unavailable",
        last_error_category=category,
        consecutive_failures=failures,
    )
    previous = registry.state_snapshots.get(config_id, {}).get("state", {})
    state = {
        **{
            key: value
            for key, value in previous.items()
            if key
            not in {
                "connected",
                "available",
                "stale",
                "error_category",
                "consecutive_failures",
            }
        },
        "connected": False,
        "available": False,
        "stale": True,
        "error_category": category,
        "consecutive_failures": failures,
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    _publish_telemetry(entry, state)
    if was_online:
        append_runtime_event("device.unavailable", entry, {"category": category})
    return state


async def apply_config(config: DeviceConfig) -> None:
    config = _resolved_config(config)
    config_id = str(config.config_id or config.id)
    candidate: MideaLanClient | None = None
    try:
        candidate = await runtime_data.connector(
            host=config.host,
            port=config.port,
            device_id=config.midea_device_id,
            token=_secret_value(config.token),
            key=_secret_value(config.key),
        )
        snapshot = await candidate.refresh()
        if not snapshot.get("connected"):
            raise MideaSetupError("unavailable")
    except MideaSetupError as exc:
        if candidate is not None:
            await _close_client(candidate, config_id)
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    except Exception as exc:
        if candidate is not None:
            await _close_client(candidate, config_id)
        logger.warning(
            "midea_setup_failed config_id=%s error=%s",
            config_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=422, detail={"error": "unreachable"}) from exc

    entry = _make_entry(config, candidate)
    old_client: MideaLanClient | None = None
    try:
        async with runtime_data.config_lock:
            lock = runtime_data.locks.setdefault(config_id, asyncio.Lock())
            async with lock:
                duplicate = next(
                    (
                        item
                        for other_id, item in registry.entries.items()
                        if other_id != config_id
                        and item.get("hardware_id") == candidate.hardware_id
                    ),
                    None,
                )
                if duplicate is not None:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "device_already_configured"},
                    )
                previous_entry = registry.get(config_id)
                if (
                    previous_entry is not None
                    and previous_entry.get("hardware_id") != candidate.hardware_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "device_identity_mismatch"},
                    )
                previous_config = runtime_data.configs.get(config_id)
                previous_state = registry.state_snapshots.get(config_id)
                old_client = runtime_data.clients.get(config_id)
                try:
                    runtime_data.configs[config_id] = config
                    runtime_data.clients[config_id] = candidate
                    registry.set(config_id, entry)
                    _publish_state(entry, snapshot)
                except Exception:
                    if previous_config is None:
                        runtime_data.configs.pop(config_id, None)
                    else:
                        runtime_data.configs[config_id] = previous_config
                    if old_client is None:
                        runtime_data.clients.pop(config_id, None)
                    else:
                        runtime_data.clients[config_id] = old_client
                    if previous_entry is None:
                        registry.entries.pop(config_id, None)
                    else:
                        registry.entries[config_id] = previous_entry
                    if previous_state is None:
                        registry.state_snapshots.pop(config_id, None)
                    else:
                        registry.state_snapshots[config_id] = previous_state
                    raise
    except Exception:
        await _close_client(candidate, config_id)
        raise
    if old_client is not None and old_client is not candidate:
        await _close_client(old_client, config_id)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"reconfigured": old_client is not None},
    )


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


async def _client_for_locked(config_id: str, entry: dict[str, Any]) -> MideaLanClient:
    cached = runtime_data.clients.get(config_id)
    if cached is not None:
        return cached
    config = runtime_data.configs.get(config_id)
    if config is None:
        raise MideaSetupError("configuration_unavailable")
    client = await runtime_data.connector(
        host=config.host,
        port=config.port,
        device_id=config.midea_device_id,
        token=_secret_value(config.token),
        key=_secret_value(config.key),
    )
    if client.hardware_id != entry.get("hardware_id"):
        await _close_client(client, config_id)
        raise MideaSetupError("device_identity_mismatch")
    runtime_data.clients[config_id] = client
    return client


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        if registry.get(config_id) is not entry:
            return {"connected": False, "available": False, "stale": True}
        try:
            client = await _client_for_locked(config_id, entry)
            snapshot = await client.refresh()
            if not snapshot.get("connected"):
                raise MideaSetupError("unavailable")
        except Exception as exc:  # noqa: BLE001 - vendor transports have broad failures
            await _discard_client(config_id)
            category = _error_category(exc)
            logger.warning(
                "midea_refresh_failed config_id=%s error=%s category=%s",
                config_id,
                type(exc).__name__,
                category,
            )
            state = _publish_unavailable(entry, category)
        else:
            was_offline = entry.get("availability") != "online"
            state = _publish_state(entry, snapshot)
            if was_offline:
                append_runtime_event("device.restored", entry)
        config = runtime_data.configs.get(config_id)
        interval = config.poll_interval_seconds if config else 30
        failures = int(entry.get("consecutive_failures", 0))
        entry["next_poll_at"] = (
            float("inf")
            if entry.get("availability") == "reauth_required"
            else time.monotonic() + min(3600, interval * (2 ** min(failures, 5)))
        )
        return state


async def execute_command(
    entry: dict[str, Any], command: str, args: dict[str, Any]
) -> dict[str, Any]:
    if command == "refresh":
        return await refresh_entry(entry)
    config_id = str(entry["config_id"])
    config = runtime_data.configs.get(config_id)
    if config is None or not config.controls_enabled:
        raise ValueError("Midea controls are disabled for this configuration")
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        try:
            client = await _client_for_locked(config_id, entry)
            snapshot = await client.execute(command, args)
            if not snapshot.get("connected"):
                raise MideaSetupError("unavailable")
        except ValueError:
            raise
        except Exception as exc:
            await _discard_client(config_id)
            category = _error_category(exc)
            _publish_unavailable(entry, category)
            raise RuntimeError(f"Midea command failed: {category}") from exc
        return _publish_state(entry, snapshot)


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
            await asyncio.gather(
                *(refresh_entry(entry) for entry in due),
                return_exceptions=True,
            )


async def close_clients() -> None:
    for config_id in list(runtime_data.clients):
        await _discard_client(config_id)


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request, *, _command_name=command_name):
            target = request.target if isinstance(request.target, dict) else {}
            config_id = str(request.config_id or target.get("config_id") or "").strip()
            if not config_id:
                raise ValueError("A configured Midea air conditioner target is required")
            entry = registry.get(config_id)
            if entry is None:
                raise ValueError("Unknown configured Midea air conditioner")
            requested_device_id = str(request.device_id or target.get("device_id") or "").strip()
            if requested_device_id and requested_device_id != str(entry["device_id"]):
                raise ValueError("Midea target does not match the configured device")
            metrics = await execute_command(entry, _command_name, request.args)
            if not metrics.get("connected"):
                raise RuntimeError("Midea air conditioner is unavailable")
            event = append_runtime_event(
                "runtime.command.received",
                entry,
                {"command": _command_name},
            )
            return {
                "event": event,
                "command": _command_name,
                "device_id": entry["device_id"],
                "config_id": config_id,
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
