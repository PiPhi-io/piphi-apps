from __future__ import annotations

import asyncio
import copy
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    create_tracked_task,
    schedule_event_delivery,
    schedule_telemetry_delivery,
)

from .schemas import TuyaDeviceConfig
from .settings import (
    INTEGRATION_ID,
    INTEGRATION_NAME,
    INTEGRATION_VERSION,
    poll_error_event_cooldown_seconds,
    poll_failure_backoff_seconds,
    poll_jitter_seconds,
    strict_config_validation,
)
from .tuya import (
    TuyaClientError,
    close_device,
    execute_command,
    heartbeat_device,
    normalize_device_type,
    open_persistent_device,
    read_device_status,
)

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
event_client = starter.event_client
config_sync = starter.config_sync
poll_tasks: dict[str, asyncio.Task[Any]] = {}
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TuyaDeviceSession:
    device: Any
    lock: asyncio.Lock


device_sessions: dict[str, TuyaDeviceSession] = {}
_SECRET_CONFIG_FIELDS = {"local_key", "api_key", "api_secret"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_status(entry: dict[str, Any]) -> dict[str, Any]:
    status = entry.get("runtime_status")
    if not isinstance(status, dict):
        status = {
            "consecutive_failures": 0,
            "last_refresh_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_error_event_at": None,
            "last_latency_ms": None,
        }
        entry["runtime_status"] = status
    return status


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def sanitize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(entry)
    config = redacted.get("config")
    if isinstance(config, dict):
        for field in _SECRET_CONFIG_FIELDS:
            if field in config:
                config[field] = "***redacted***"
    return redacted


def make_entry(config: TuyaDeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    normalized_device_type = normalize_device_type(
        config.device_type, alias=config.alias
    )
    return {
        **identity,
        "host": config.host,
        "alias": config.alias or config.tuya_device_id,
        "tuya_device_id": config.tuya_device_id,
        "device_type": normalized_device_type,
        "protocol_version": config.version,
        "switch": config.switch,
        "poll_interval_seconds": config.poll_interval_seconds,
        "config": config.model_dump(),
        "runtime_status": {
            "consecutive_failures": 0,
            "last_refresh_at": None,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_error_event_at": None,
            "last_latency_ms": None,
        },
    }


def emit_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    *,
    severity: str = "info",
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity=severity,
    )
    registry.append_event(event)
    if runtime.auth.container_id and runtime.auth.internal_token:
        schedule_event_delivery(
            process_state=runtime.process_state,
            event_client=event_client,
            auth_context=runtime.auth,
            event_type=event_type,
            device=device,
            payload=payload or {},
            source=INTEGRATION_ID,
            severity=severity,
        )
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def ensure_unique_device_identity(config: TuyaDeviceConfig) -> None:
    config_id = str(config.id)
    host = str(config.host).strip().lower()
    tuya_device_id = str(config.tuya_device_id).strip().lower()
    for existing in registry.entries.values():
        existing_config_id = str(existing.get("config_id") or existing.get("id") or "")
        if existing_config_id == config_id:
            continue
        existing_host = str(existing.get("host") or "").strip().lower()
        existing_device_id = str(existing.get("tuya_device_id") or "").strip().lower()
        if host and host == existing_host:
            raise TuyaClientError(
                f"A Tuya device with host {config.host} is already configured as config_id={existing_config_id}"
            )
        if tuya_device_id and tuya_device_id == existing_device_id:
            raise TuyaClientError(
                f"A Tuya device with tuya_device_id {config.tuya_device_id} is already configured as config_id={existing_config_id}"
            )


def find_entry(
    *, config_id: str | None = None, device_id: str | None = None
) -> dict[str, Any] | None:
    if config_id:
        entry = registry.get(config_id)
        if entry is not None:
            return entry
    if device_id:
        for entry in registry.entries.values():
            if str(entry.get("device_id")) == str(device_id):
                return entry
    return None


def _build_session_for_entry(entry: dict[str, Any]) -> TuyaDeviceSession:
    config = TuyaDeviceConfig.model_validate(entry["config"])
    return TuyaDeviceSession(device=open_persistent_device(config), lock=asyncio.Lock())


def get_device_session(entry: dict[str, Any]) -> TuyaDeviceSession:
    config_id = str(entry["config_id"])
    session = device_sessions.get(config_id)
    if session is None:
        session = _build_session_for_entry(entry)
        device_sessions[config_id] = session
    return session


def close_device_session(config_id: str) -> bool:
    session = device_sessions.pop(config_id, None)
    if session is None:
        return False
    try:
        close_device(session.device)
    except Exception:
        return False
    return True


async def _with_persistent_session(entry: dict[str, Any], operation):
    config_id = str(entry["config_id"])
    last_error: Exception | None = None
    for attempt in range(2):
        session = get_device_session(entry)
        async with session.lock:
            try:
                return await operation(session, attempt)
            except Exception as exc:
                last_error = exc
                close_device_session(config_id)
                if attempt == 1:
                    raise
    assert last_error is not None
    raise last_error


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config = TuyaDeviceConfig.model_validate(entry["config"])
    status = _runtime_status(entry)
    try:

        async def _refresh(session: TuyaDeviceSession, attempt: int):
            if attempt > 0:
                await heartbeat_device(session.device)
            return await read_device_status(config, device=session.device)

        snapshot = await _with_persistent_session(entry, _refresh)
        now = _utc_now()
        status["consecutive_failures"] = 0
        status["last_refresh_at"] = now
        status["last_success_at"] = now
        status["last_error"] = None
        status["last_latency_ms"] = snapshot.metrics.get("latency_ms")
        state = {
            **snapshot.metrics,
            "host": entry["host"],
            "alias": entry["alias"],
            "tuya_device_id": entry["tuya_device_id"],
            "device_type": entry["device_type"],
            "config_id": entry["config_id"],
            "last_refresh_at": status["last_refresh_at"],
            "last_success_at": status["last_success_at"],
            "consecutive_failures": status["consecutive_failures"],
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        entry["latest_metrics"] = snapshot.metrics
        entry["latest_units"] = snapshot.units
        entry["latest_raw"] = snapshot.raw
        logger.info(
            "Tuya refresh succeeded for config_id=%s device_type=%s host=%s latency_ms=%s",
            entry["config_id"],
            entry["device_type"],
            entry["host"],
            snapshot.metrics.get("latency_ms"),
        )
        emit_runtime_event(
            "tuya.status.refreshed",
            entry,
            {
                "host": entry["host"],
                "tuya_device_id": entry["tuya_device_id"],
                "dp_count": snapshot.metrics.get("dp_count", 0),
                "persistent_session": True,
            },
        )
        return state
    except Exception as exc:
        reason = str(exc)
        now = _utc_now()
        previous_error = str(status.get("last_error") or "")
        previous_error_event_at = status.get("last_error_event_at")
        status["consecutive_failures"] = (
            _safe_int(status.get("consecutive_failures")) + 1
        )
        status["last_refresh_at"] = now
        status["last_failure_at"] = now
        status["last_error"] = reason
        state = {
            "connected": False,
            "host": entry["host"],
            "alias": entry["alias"],
            "tuya_device_id": entry["tuya_device_id"],
            "device_type": entry["device_type"],
            "config_id": entry["config_id"],
            "error": reason,
            "last_refresh_at": status["last_refresh_at"],
            "last_failure_at": status["last_failure_at"],
            "consecutive_failures": status["consecutive_failures"],
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        entry["latest_metrics"] = {"connected": False}
        entry["latest_units"] = {"connected": "bool"}
        entry["latest_raw"] = {"error": reason}
        logger.warning(
            "Tuya refresh failed for config_id=%s device_type=%s host=%s failures=%s error=%s",
            entry["config_id"],
            entry["device_type"],
            entry["host"],
            status["consecutive_failures"],
            reason,
        )
        should_emit_error = (
            reason != previous_error
            or not previous_error_event_at
            or (
                datetime.now(timezone.utc).timestamp()
                - datetime.fromisoformat(str(previous_error_event_at)).timestamp()
            )
            >= poll_error_event_cooldown_seconds()
        )
        if should_emit_error:
            status["last_error_event_at"] = now
            emit_runtime_event(
                "tuya.status.error",
                entry,
                {
                    "host": entry["host"],
                    "tuya_device_id": entry["tuya_device_id"],
                    "error": reason,
                    "consecutive_failures": status["consecutive_failures"],
                },
                severity="warning",
            )
        return state


def _schedule_latest_telemetry(entry: dict[str, Any]) -> None:
    latest_metrics = entry.get("latest_metrics") or {}
    latest_units = entry.get("latest_units") or {}
    if not latest_metrics:
        return
    if not (runtime.auth.container_id and runtime.auth.internal_token):
        return
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        config_id=entry.get("config_id"),
        metrics=latest_metrics,
        units=latest_units,
    )


def stop_poll_task(config_id: str) -> bool:
    task = poll_tasks.pop(config_id, None)
    if task is None:
        return False
    if not task.done():
        task.cancel()
    return True


async def _poll_entry_loop(config_id: str) -> None:
    try:
        while True:
            entry = registry.get(config_id)
            if entry is None:
                return
            config = TuyaDeviceConfig.model_validate(entry["config"])
            status = _runtime_status(entry)
            base_interval = max(10, int(config.poll_interval_seconds))
            failure_backoff = min(_safe_int(status.get("consecutive_failures")), 4) * (
                poll_failure_backoff_seconds()
            )
            jitter = random.uniform(0.0, poll_jitter_seconds())
            await asyncio.sleep(base_interval + failure_backoff + jitter)
            entry = registry.get(config_id)
            if entry is None:
                return
            await refresh_entry(entry)
            _schedule_latest_telemetry(entry)
    except asyncio.CancelledError:
        raise


def start_poll_task(entry: dict[str, Any]) -> asyncio.Task[Any]:
    config_id = str(entry["config_id"])
    stop_poll_task(config_id)
    task = create_tracked_task(
        _poll_entry_loop(config_id),
        process_state=runtime.process_state,
    )
    poll_tasks[config_id] = task
    task.add_done_callback(lambda _task, cid=config_id: poll_tasks.pop(cid, None))
    return task


async def apply_config(config: TuyaDeviceConfig) -> None:
    config_id = str(config.id)
    previous_entry = registry.get(config_id)
    previous_entry_copy = copy.deepcopy(previous_entry) if previous_entry else None
    previous_snapshot = copy.deepcopy(registry.state_snapshots.get(config_id))

    ensure_unique_device_identity(config)
    entry = make_entry(config)
    stop_poll_task(config_id)
    close_device_session(config_id)
    registry.set(config_id, entry)
    state = await refresh_entry(entry)

    if strict_config_validation() and not bool(state.get("connected")):
        reason = str(state.get("error") or "Initial Tuya validation failed")
        logger.error(
            "Tuya config validation failed for config_id=%s host=%s device_type=%s error=%s",
            config_id,
            entry["host"],
            entry["device_type"],
            reason,
        )
        emit_runtime_event(
            "tuya.config.validation_failed",
            entry,
            {
                "host": entry["host"],
                "alias": entry["alias"],
                "tuya_device_id": entry["tuya_device_id"],
                "device_type": entry["device_type"],
                "error": reason,
            },
            severity="error",
        )
        registry.remove(config_id)
        close_device_session(config_id)
        if previous_entry_copy is not None:
            registry.set(config_id, previous_entry_copy)
            if previous_snapshot is not None:
                registry.state_snapshots[config_id] = previous_snapshot
            start_poll_task(previous_entry_copy)
        else:
            registry.state_snapshots.pop(config_id, None)
        raise TuyaClientError(
            f"Config validation failed for Tuya device {entry['alias']}: {reason}"
        )

    _schedule_latest_telemetry(entry)
    logger.info(
        "Applied Tuya config_id=%s device_type=%s host=%s",
        config_id,
        entry["device_type"],
        entry["host"],
    )
    emit_runtime_event(
        "tuya.config.applied",
        entry,
        {
            "host": entry["host"],
            "alias": entry["alias"],
            "tuya_device_id": entry["tuya_device_id"],
            "device_type": entry["device_type"],
            "poll_interval_seconds": entry["poll_interval_seconds"],
            "persistent_session": True,
        },
    )
    start_poll_task(entry)


async def remove_config(config_id: str) -> bool:
    stop_poll_task(config_id)
    close_device_session(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    emit_runtime_event(
        "tuya.config.removed",
        entry,
        {
            "host": entry.get("host"),
            "alias": entry.get("alias"),
            "tuya_device_id": entry.get("tuya_device_id"),
        },
    )
    return True


async def execute_command_for_entry(
    entry: dict[str, Any],
    command_name: str,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if command_name == "refresh":
        state = await refresh_entry(entry)
        emit_runtime_event(
            "tuya.command.executed",
            entry,
            {"command": command_name, "args": args or {}, "refreshed": True},
        )
        _schedule_latest_telemetry(entry)
        return {"result": {"command": command_name}, "state": state}

    config = TuyaDeviceConfig.model_validate(entry["config"])

    async def _execute(session: TuyaDeviceSession, _attempt: int):
        return await execute_command(
            config, command_name, args or {}, device=session.device
        )

    result = await _with_persistent_session(entry, _execute)
    logger.info(
        "Executed Tuya command config_id=%s command=%s host=%s",
        entry["config_id"],
        command_name,
        entry["host"],
    )
    state = await refresh_entry(entry)
    emit_runtime_event(
        "tuya.command.executed",
        entry,
        {"command": command_name, "args": args or {}, "refreshed": True},
    )
    _schedule_latest_telemetry(entry)
    return {"result": result.raw, "state": state}


async def refresh_all_entries() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        results.append(await refresh_entry(entry))
        _schedule_latest_telemetry(entry)
    return results


async def shutdown_runtime_resources() -> None:
    tasks = list(poll_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    poll_tasks.clear()
    for config_id in list(device_sessions.keys()):
        close_device_session(config_id)


__all__ = [
    "TuyaClientError",
    "apply_config",
    "close_device_session",
    "config_sync",
    "device_sessions",
    "ensure_unique_device_identity",
    "event_client",
    "execute_command_for_entry",
    "find_entry",
    "get_device_session",
    "get_entry_or_404",
    "poll_tasks",
    "refresh_all_entries",
    "refresh_entry",
    "registry",
    "runtime",
    "sanitize_entry",
    "shutdown_runtime_resources",
    "start_poll_task",
    "starter",
    "stop_poll_task",
    "telemetry",
]
starter.state.provide(refresh_all_entries, source=INTEGRATION_ID)
