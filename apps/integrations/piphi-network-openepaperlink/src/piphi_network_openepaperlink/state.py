from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .ap import AccessPointSnapshot, fetch_snapshot
from .contract import CAPABILITIES, COMMANDS
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
config_sync = starter.config_sync
automations = AutomationRegistry()

capabilities = CAPABILITIES
commands = COMMANDS
refresh_locks: dict[str, asyncio.Lock] = {}
snapshot_fetcher = fetch_snapshot


def _stable_id(kind: str, config_id: str, source_id: str = "") -> str:
    digest = hashlib.sha256(f"{INTEGRATION_ID}\0{config_id}\0{source_id}".encode()).hexdigest()[:20]
    return f"oepl-{kind}-{digest}"


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    config_id = str(config.config_id or config.id)
    return {
        **identity,
        "config_id": config_id,
        "device_id": _stable_id("ap", config_id),
        "alias": config.alias,
        "config": redact(config.model_dump()),
        "consecutive_failures": 0,
        "inventory_initialized": False,
        "tag_ids": [],
    }


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


def _apply_snapshot(entry: dict[str, Any], snapshot: AccessPointSnapshot) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    previous_tags = set(entry.get("tag_ids") or [])
    current_tags = _tag_ids(config_id, snapshot)
    had_baseline = bool(entry.get("inventory_initialized"))
    entry["tag_ids"] = sorted(current_tags)
    entry["inventory_initialized"] = True
    if had_baseline:
        for tag_id in sorted(current_tags - previous_tags):
            append_runtime_event(
                "tag.discovered",
                {**entry, "device_id": tag_id},
                {"tag_device_id": tag_id},
            )
        for tag_id in sorted(previous_tags - current_tags):
            append_runtime_event(
                "tag.removed",
                {**entry, "device_id": tag_id},
                {"tag_device_id": tag_id},
            )
    metrics = _success_metrics(snapshot)
    entry["last_good"] = metrics.copy()
    entry["consecutive_failures"] = 0
    entry["status"] = "available"
    return metrics


async def apply_config(
    config: DeviceConfig,
    *,
    restored: bool = False,
    allow_unavailable: bool = False,
) -> None:
    """Probe first, then atomically replace the active entry."""
    candidate = make_entry(config)
    existing = registry.get(candidate["config_id"])
    if existing is not None:
        candidate["tag_ids"] = list(existing.get("tag_ids") or [])
        candidate["inventory_initialized"] = bool(existing.get("inventory_initialized"))
        candidate["last_good"] = dict(existing.get("last_good") or {})
    try:
        snapshot = await snapshot_fetcher(config.host)
    except (httpx.HTTPError, OSError, TimeoutError, TypeError, ValueError):
        if not allow_unavailable:
            raise ConnectionError("OpenEPaperLink access point is unavailable") from None
        candidate["status"] = "unavailable"
        candidate["consecutive_failures"] = 1
        candidate["next_poll_at"] = time.monotonic() + 60
        registry.set(candidate["config_id"], candidate)
        registry.update_state(
            candidate["config_id"],
            {
                **dict(candidate.get("last_good") or {}),
                "connected": False,
                "stale": bool(candidate.get("last_good")),
                "reason": "ap_fetch_failed",
                "consecutive_failures": 1,
            },
            device_id=candidate["device_id"],
        )
    else:
        metrics = _apply_snapshot(candidate, snapshot)
        candidate["next_poll_at"] = time.monotonic() + config.poll_interval_seconds
        registry.set(candidate["config_id"], candidate)
        registry.update_state(candidate["config_id"], metrics, device_id=candidate["device_id"])
        _deliver_metrics(candidate, metrics)
    append_runtime_event(
        "runtime.config.restored" if restored else "runtime.config.applied",
        candidate,
        {"restored": restored},
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
    async with refresh_locks.setdefault(config_id, asyncio.Lock()):
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
                append_runtime_event(
                    "access_point.unavailable", entry, {"reason": "ap_fetch_failed"}
                )
            return state
        metrics = _apply_snapshot(entry, snapshot)
        entry["next_poll_at"] = time.monotonic() + config.poll_interval_seconds
        registry.update_state(config_id, metrics, device_id=entry["device_id"])
        if previous_status == "unavailable":
            append_runtime_event("access_point.recovered", entry)
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
    entry = registry.remove(config_id)
    if entry is None:
        return False
    refresh_locks.pop(config_id, None)
    append_runtime_event(
        "runtime.config.removed", entry, {"removed_tag_count": len(entry.get("tag_ids") or [])}
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
