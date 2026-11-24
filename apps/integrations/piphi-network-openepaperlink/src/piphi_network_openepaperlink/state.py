from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    RuntimeConfigSnapshot,
    build_local_event_record,
    build_runtime_identity,
    build_sync_response,
    create_runtime_starter,
    reconcile_config_ids,
    schedule_event_delivery,
    schedule_telemetry_delivery,
)

from .ap import AccessPointSnapshot, fetch_snapshot
from .contract import CAPABILITIES, COMMANDS
from .persistence import load_state, save_state
from .privacy import redact
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
events = starter.event_client
config_sync = starter.config_sync
automations = AutomationRegistry()
for _event_type, _label in {
    "runtime.config.applied": "Access-point configuration applied",
    "runtime.config.restored": "Access-point configuration restored",
    "runtime.config.removed": "Access-point configuration removed",
    "access_point.unavailable": "Access point became unavailable",
    "access_point.recovered": "Access point recovered",
    "tag.discovered": "Tag discovered",
    "tag.removed": "Tag removed",
}.items():
    automations.event(_event_type, label=_label)

capabilities = CAPABILITIES
commands = COMMANDS
refresh_locks: dict[str, asyncio.Lock] = {}
config_lock = asyncio.Lock()
snapshot_fetcher = fetch_snapshot
state_loader = load_state
state_saver = save_state
event_scheduler = schedule_event_delivery
persisted_state: dict[str, dict[str, Any]] = {}


@dataclass(slots=True)
class PreparedConfig:
    entry: dict[str, Any]
    state: dict[str, Any]
    transitions: list[tuple[str, str]]
    deliver: bool


def _stable_id(kind: str, config_id: str, source_id: str = "") -> str:
    digest = hashlib.sha256(f"{INTEGRATION_ID}\0{config_id}\0{source_id}".encode()).hexdigest()[:20]
    return f"oepl-{kind}-{digest}"


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    config_id = str(config.config_id or config.id)
    entry = {
        **identity,
        "config_id": config_id,
        "device_id": _stable_id("ap", config_id),
        "alias": config.alias,
        "config": redact(config.model_dump()),
        "consecutive_failures": 0,
        "inventory_initialized": False,
        "tag_ids": [],
    }
    restored = persisted_state.get(config_id)
    if restored and restored.get("device_id") == entry["device_id"]:
        entry.update(deepcopy(restored))
    return entry


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=redact(payload or {}),
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    task = event_scheduler(
        process_state=runtime.process_state,
        event_client=events,
        auth_context=runtime.auth,
        event_type=event_type,
        device=device,
        payload=redact(payload or {}),
        source=INTEGRATION_ID,
        severity="info",
    )
    task.add_done_callback(
        lambda completed: completed.exception() if not completed.cancelled() else None
    )
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown access-point configuration")
    return entry


def _tag_ids(config_id: str, snapshot: AccessPointSnapshot) -> set[str]:
    return {_stable_id("tag", config_id, tag.source_id) for tag in snapshot.tags}


def _success_metrics(snapshot: AccessPointSnapshot) -> dict[str, Any]:
    return {
        "connected": True,
        "stale": False,
        "ap_tag_count": snapshot.tag_count,
        "ap_pending_transfer_count": snapshot.pending_transfer_count,
        "last_success_at": datetime.now(UTC).isoformat(),
        "consecutive_failures": 0,
    }


def _apply_snapshot(
    entry: dict[str, Any], snapshot: AccessPointSnapshot
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    config_id = str(entry["config_id"])
    previous_tags = set(entry.get("tag_ids") or [])
    current_tags = _tag_ids(config_id, snapshot)
    had_baseline = bool(entry.get("inventory_initialized"))
    entry["tag_ids"] = sorted(current_tags)
    entry["inventory_initialized"] = True
    transitions: list[tuple[str, str]] = []
    if had_baseline:
        transitions.extend(
            ("tag.discovered", tag_id) for tag_id in sorted(current_tags - previous_tags)
        )
        transitions.extend(
            ("tag.removed", tag_id) for tag_id in sorted(previous_tags - current_tags)
        )
    metrics = _success_metrics(snapshot)
    entry["last_good"] = metrics.copy()
    entry["consecutive_failures"] = 0
    entry["status"] = "available"
    return metrics, transitions


def _persistable_entries() -> dict[str, dict[str, Any]]:
    return {
        str(config_id): {
            "device_id": str(entry["device_id"]),
            "tag_ids": list(entry.get("tag_ids") or []),
            "last_good": dict(entry.get("last_good") or {}),
            "inventory_initialized": bool(entry.get("inventory_initialized")),
            "status": str(entry.get("status") or "initializing"),
            "consecutive_failures": int(entry.get("consecutive_failures") or 0),
        }
        for config_id, entry in registry.entries.items()
    }


async def persist_runtime_state() -> None:
    records = _persistable_entries()
    await asyncio.to_thread(state_saver, records)
    persisted_state.clear()
    persisted_state.update(deepcopy(records))


async def restore_runtime_state() -> None:
    try:
        records = await asyncio.to_thread(state_loader)
    except (OSError, TypeError, ValueError):
        logger.exception("openepaperlink_state_restore_failed")
        records = {}
    persisted_state.clear()
    persisted_state.update(records)


async def _prepare_config(config: DeviceConfig, *, allow_unavailable: bool) -> PreparedConfig:
    candidate = make_entry(config)
    existing = registry.get(candidate["config_id"])
    if existing is not None:
        for key in (
            "tag_ids",
            "inventory_initialized",
            "last_good",
            "status",
            "consecutive_failures",
        ):
            if key in existing:
                candidate[key] = deepcopy(existing[key])
    try:
        snapshot = await snapshot_fetcher(config.host)
    except (httpx.HTTPError, OSError, TimeoutError, TypeError, ValueError):
        if not allow_unavailable:
            raise ConnectionError("OpenEPaperLink access point is unavailable") from None
        candidate["status"] = "unavailable"
        candidate["consecutive_failures"] = int(candidate.get("consecutive_failures") or 0) + 1
        candidate["next_poll_at"] = time.monotonic() + 60
        state = {
            **dict(candidate.get("last_good") or {}),
            "connected": False,
            "stale": bool(candidate.get("last_good")),
            "reason": "ap_fetch_failed",
            "consecutive_failures": candidate["consecutive_failures"],
        }
        return PreparedConfig(candidate, state, [], False)
    metrics, transitions = _apply_snapshot(candidate, snapshot)
    candidate["next_poll_at"] = time.monotonic() + config.poll_interval_seconds
    return PreparedConfig(candidate, metrics, transitions, True)


def _install_prepared(prepared: PreparedConfig) -> None:
    entry = prepared.entry
    registry.set(entry["config_id"], entry)
    registry.update_state(entry["config_id"], prepared.state, device_id=entry["device_id"])


def _emit_prepared(prepared: PreparedConfig, *, event_type: str) -> None:
    entry = prepared.entry
    for transition, tag_id in prepared.transitions:
        append_runtime_event(
            transition,
            {**entry, "device_id": tag_id},
            {"tag_device_id": tag_id},
        )
    append_runtime_event(event_type, entry, {"restored": event_type.endswith("restored")})
    if prepared.deliver:
        _deliver_metrics(entry, prepared.state)


def _registry_backup() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    return (
        deepcopy(registry.entries),
        deepcopy(registry.state_snapshots),
        deepcopy(registry.recent_events),
    )


def _restore_registry(backup: tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]) -> None:
    entries, snapshots, events = backup
    registry.entries.clear()
    registry.entries.update(entries)
    registry.state_snapshots.clear()
    registry.state_snapshots.update(snapshots)
    registry.recent_events.clear()
    registry.recent_events.extend(events)


async def apply_config(
    config: DeviceConfig,
    *,
    restored: bool = False,
    allow_unavailable: bool = False,
) -> None:
    """Probe first, then atomically replace the active entry and durable state."""
    async with config_lock:
        prepared = await _prepare_config(config, allow_unavailable=allow_unavailable)
        backup = _registry_backup()
        try:
            _install_prepared(prepared)
            await persist_runtime_state()
        except Exception:
            _restore_registry(backup)
            raise
        _emit_prepared(
            prepared,
            event_type="runtime.config.restored" if restored else "runtime.config.applied",
        )


async def apply_config_snapshot(
    snapshot: RuntimeConfigSnapshot,
    *,
    restored: bool = False,
    allow_unavailable: bool = False,
) -> Any:
    """Stage every connection before atomically committing a complete Core snapshot."""
    configs = [DeviceConfig.model_validate(config.model_dump()) for config in snapshot.configs]
    async with config_lock:
        if config_sync.is_stale(snapshot):
            return config_sync.build_stale_response(
                snapshot=snapshot, active_config_ids=registry.ids()
            )
        prepared = [
            await _prepare_config(config, allow_unavailable=allow_unavailable) for config in configs
        ]
        incoming_ids = [str(item.entry["config_id"]) for item in prepared]
        removed_ids, _ = reconcile_config_ids(active_ids=registry.ids(), incoming_ids=incoming_ids)
        backup = _registry_backup()
        previous_generation = config_sync.get_current_generation()
        removed_entries: dict[str, dict[str, Any]] = {}
        for config_id in removed_ids:
            existing = registry.get(config_id)
            if existing is not None:
                removed_entries[config_id] = deepcopy(existing)
        try:
            for config_id in removed_ids:
                registry.remove(config_id)
                refresh_locks.pop(config_id, None)
            event_type = "runtime.config.restored" if restored else "runtime.config.applied"
            for item in prepared:
                _install_prepared(item)
            generation = config_sync.mark_generation(snapshot.generation)
            await persist_runtime_state()
        except Exception:
            _restore_registry(backup)
            runtime.process_state.current_generation = previous_generation
            raise
        for item in prepared:
            _emit_prepared(item, event_type=event_type)
        for config_id, entry in removed_entries.items():
            append_runtime_event(
                "runtime.config.removed",
                entry,
                {"removed_tag_count": len(entry.get("tag_ids") or [])},
            )
        return build_sync_response(
            status="synced",
            container_id=snapshot.container_id,
            reason=snapshot.reason,
            generation=generation,
            applied=incoming_ids,
            removed=removed_ids,
            active_config_ids=registry.ids(),
            metadata={
                "applied_count": len(incoming_ids),
                "removed_count": len(removed_ids),
                "atomic": True,
            },
        )


def _deliver_metrics(entry: dict[str, Any], metrics: dict[str, Any]) -> None:
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={"ap_tag_count": "count", "ap_pending_transfer_count": "count"},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    async with refresh_locks.setdefault(config_id, asyncio.Lock()), config_lock:
        current_entry = registry.get(config_id)
        if current_entry is None:
            raise HTTPException(status_code=404, detail="unknown access-point configuration")
        return await _refresh_entry_locked(current_entry)


async def _refresh_entry_locked(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    config = DeviceConfig.model_validate(entry["config"])
    previous_status = str(entry.get("status") or "initializing")
    try:
        snapshot = await snapshot_fetcher(config.host)
    except (httpx.HTTPError, OSError, TimeoutError, TypeError, ValueError):
        logger.warning("openepaperlink_refresh_failed config_id=%s", config_id)
        failures = int(entry.get("consecutive_failures") or 0) + 1
        entry["consecutive_failures"] = failures
        entry["status"] = "unavailable"
        entry["next_poll_at"] = time.monotonic() + min(900, 60 * (2 ** min(failures - 1, 4)))
        state = {
            **dict(entry.get("last_good") or {}),
            "connected": False,
            "stale": bool(entry.get("last_good")),
            "reason": "ap_fetch_failed",
            "consecutive_failures": failures,
        }
        registry.update_state(config_id, state, device_id=entry["device_id"])
        if previous_status not in {"initializing", "unavailable"}:
            append_runtime_event("access_point.unavailable", entry, {"reason": "ap_fetch_failed"})
        try:
            await persist_runtime_state()
        except (OSError, TypeError, ValueError):
            logger.exception("openepaperlink_state_persist_failed config_id=%s", config_id)
        return state
    metrics, transitions = _apply_snapshot(entry, snapshot)
    entry["next_poll_at"] = time.monotonic() + config.poll_interval_seconds
    registry.update_state(config_id, metrics, device_id=entry["device_id"])
    for transition, tag_id in transitions:
        append_runtime_event(
            transition,
            {**entry, "device_id": tag_id},
            {"tag_device_id": tag_id},
        )
    if previous_status == "unavailable":
        append_runtime_event("access_point.recovered", entry)
    try:
        await persist_runtime_state()
    except (OSError, TypeError, ValueError):
        logger.exception("openepaperlink_state_persist_failed config_id=%s", config_id)
    _deliver_metrics(entry, metrics)
    return metrics


async def poll_access_points() -> None:
    while True:
        await asyncio.sleep(5)
        now = time.monotonic()
        for entry in list(registry.entries.values()):
            if entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 300
            await refresh_entry(entry)


async def remove_config(config_id: str) -> bool:
    async with config_lock:
        backup = _registry_backup()
        entry = registry.remove(config_id)
        if entry is None:
            return False
        try:
            refresh_locks.pop(config_id, None)
            await persist_runtime_state()
        except Exception:
            _restore_registry(backup)
            raise
        append_runtime_event(
            "runtime.config.removed",
            entry,
            {"removed_tag_count": len(entry.get("tag_ids") or [])},
        )
        return True


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request: Any, *, _command_name: str = command_name) -> dict[str, Any]:
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            config_id = str(request.config_id or target.get("config_id") or "")
            device_id = str(request.device_id or target.get("device_id") or "")
            if not config_id or not device_id:
                raise ValueError("A configured access-point target is required")
            entry = registry.get(config_id)
            if entry is None or device_id != entry["device_id"]:
                raise ValueError("Unknown configured access-point target")
            metrics = await refresh_entry(entry)
            if not metrics.get("connected"):
                raise RuntimeError("Access-point data is unavailable")
            return {
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "ap_tag_count": metrics["ap_tag_count"],
                "ap_pending_transfer_count": metrics["ap_pending_transfer_count"],
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
