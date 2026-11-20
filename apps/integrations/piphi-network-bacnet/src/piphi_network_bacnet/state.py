from __future__ import annotations

import asyncio
import os
import random
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationActionRequest,
    AutomationActionResult,
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .bacnet_client import BacnetReadError, BacnetReader, BacpypesReader, DeviceSnapshot
from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
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
bacnet_reader: BacnetReader = BacpypesReader()
runtime_configs: dict[str, DeviceConfig] = {}
poll_tasks: dict[str, asyncio.Task[None]] = {}
poll_status: dict[str, dict[str, Any]] = {}
MAX_POLL_BACKOFF_SECONDS = 900.0
POLL_JITTER_RATIO = 0.1


def set_bacnet_reader(reader: BacnetReader) -> None:
    global bacnet_reader
    bacnet_reader = reader


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "alias": config.alias,
        "profile": config.profile,
        "device_instance": config.device_instance,
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
        raise HTTPException(status_code=404, detail="unknown BACnet configuration")
    return entry


def _snapshot_state(snapshot: DeviceSnapshot, *, config_id: str, device_id: str) -> dict[str, Any]:
    return {
        "connected": True,
        "stale": False,
        "config_id": config_id,
        "device_id": device_id,
        "profile": "kaiterra_sensedge_mini",
        "device": {
            "device_instance": snapshot.device_instance,
            "object_name": snapshot.object_name,
            "vendor_id": snapshot.vendor_id,
            "model_name": snapshot.model_name,
            "firmware_revision": snapshot.firmware_revision,
            "application_software_version": snapshot.application_software_version,
            "protocol_version": snapshot.protocol_version,
            "protocol_revision": snapshot.protocol_revision,
            "segmentation_supported": snapshot.segmentation_supported,
            "max_apdu_length": snapshot.max_apdu_length,
            "database_revision": snapshot.database_revision,
        },
        "metrics": snapshot.metrics,
        "units": snapshot.units,
        "points": [
            {
                "object_instance": reading.object_instance,
                "object_name": reading.object_name,
                "metric": reading.metric,
                "status_flags": reading.status_flags,
                "reliability": reading.reliability,
                "out_of_service": reading.out_of_service,
            }
            for reading in snapshot.readings
        ],
        "sampled_at": datetime.now(tz=UTC).isoformat(),
    }


def _store_snapshot(
    config_id: str,
    entry: dict[str, Any],
    snapshot: DeviceSnapshot,
) -> None:
    state = _snapshot_state(
        snapshot,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
    )
    registry.update_state(
        config_id,
        state,
        device_id=str(entry["device_id"]),
    )
    previous_status = poll_status.get(config_id, {})
    poll_status[config_id] = {
        "connected": True,
        "last_success_at": state["sampled_at"],
        "last_error": None,
        "reading_count": len(snapshot.readings),
        "consecutive_failures": 0,
    }
    if previous_status.get("connected") is False and previous_status.get("last_failure_at"):
        append_runtime_event(
            "runtime.device.recovered",
            entry,
            {"recovered_at": state["sampled_at"]},
        )
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=snapshot.metrics,
        units=snapshot.units,
    )


async def _read_and_store(config_id: str) -> DeviceSnapshot:
    config = runtime_configs.get(config_id)
    entry = registry.get(config_id)
    if config is None or entry is None:
        raise BacnetReadError("The BACnet configuration is no longer active.")
    snapshot = await bacnet_reader.read_snapshot(config)
    _store_snapshot(config_id, entry, snapshot)
    return snapshot


async def poll_once(config_id: str) -> bool:
    try:
        await _read_and_store(config_id)
        return True
    except BacnetReadError:
        entry = registry.get(config_id)
        previous = poll_status.get(config_id, {})
        failed_at = datetime.now(tz=UTC).isoformat()
        failures = int(previous.get("consecutive_failures", 0)) + 1
        poll_status[config_id] = {
            **previous,
            "connected": False,
            "last_error": "bacnet_read_failed",
            "last_failure_at": failed_at,
            "consecutive_failures": failures,
        }
        if entry is not None:
            previous_state = dict(
                registry.state_snapshots.get(config_id, {}).get("state", {})
            )
            registry.update_state(
                config_id,
                {
                    **previous_state,
                    "connected": False,
                    "stale": bool(previous_state.get("sampled_at")),
                    "config_id": str(entry["config_id"]),
                    "device_id": str(entry["device_id"]),
                    "profile": "kaiterra_sensedge_mini",
                    "error": "bacnet_read_failed",
                    "last_failure_at": failed_at,
                    "last_success_at": previous.get("last_success_at"),
                },
                device_id=str(entry["device_id"]),
            )
            if previous.get("connected") is True:
                append_runtime_event(
                    "runtime.device.unavailable",
                    entry,
                    {"failed_at": failed_at, "reason": "bacnet_read_failed"},
                )
        return False


def next_poll_delay(interval_seconds: int, consecutive_failures: int) -> float:
    """Return capped exponential failure backoff with bounded positive jitter."""
    exponent = max(0, min(consecutive_failures, 6))
    base = min(float(interval_seconds) * (2**exponent), MAX_POLL_BACKOFF_SECONDS)
    return min(
        base + random.uniform(0.0, base * POLL_JITTER_RATIO),
        MAX_POLL_BACKOFF_SECONDS,
    )


async def _poll_config(config_id: str, interval_seconds: int) -> None:
    delay = float(interval_seconds)
    while config_id in runtime_configs:
        await asyncio.sleep(delay)
        if config_id not in runtime_configs:
            break
        succeeded = await poll_once(config_id)
        failures = int(poll_status.get(config_id, {}).get("consecutive_failures", 0))
        delay = (
            float(interval_seconds)
            if succeeded
            else next_poll_delay(interval_seconds, failures)
        )


async def _stop_poll_task(config_id: str) -> None:
    task = poll_tasks.pop(config_id, None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def apply_config(config: DeviceConfig) -> None:
    config_id = str(config.config_id or config.id)
    previous = runtime_configs.get(config_id)
    if previous is not None and (
        previous.local_address != config.local_address
        or previous.local_device_instance != config.local_device_instance
    ):
        raise BacnetReadError(
            "Changing the active BACnet client address requires removing the old configuration first."
        )

    # Probe the exact target and profile before replacing active state. A failed
    # setup or reconfiguration therefore leaves the previous poller and snapshot
    # untouched.
    snapshot = await bacnet_reader.read_snapshot(config)
    await _stop_poll_task(config_id)
    entry = make_entry(config)
    registry.set(config_id, entry)
    runtime_configs[config_id] = config
    _store_snapshot(config_id, entry, snapshot)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"profile": config.profile, "poll_interval_seconds": config.poll_interval_seconds},
    )
    poll_tasks[config_id] = asyncio.create_task(
        _poll_config(config_id, config.poll_interval_seconds),
        name=f"bacnet-poll-{config_id}",
    )


async def remove_config(config_id: str) -> bool:
    await _stop_poll_task(config_id)
    runtime_configs.pop(config_id, None)
    poll_status.pop(config_id, None)
    if not runtime_configs:
        await bacnet_reader.close()
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"profile": entry.get("profile")},
    )
    return True


async def shutdown_runtime() -> None:
    for config_id in list(poll_tasks):
        await _stop_poll_task(config_id)
    await bacnet_reader.close()


async def reset_runtime_state() -> None:
    await shutdown_runtime()
    runtime_configs.clear()
    poll_status.clear()
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await poll_once(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)


async def _refresh_device(request: AutomationActionRequest) -> AutomationActionResult:
    config_id = str(request.config_id or "").strip()
    if not config_id or config_id not in runtime_configs:
        return AutomationActionResult.failure(
            "Unknown BACnet configuration.",
            retryable=False,
        )
    try:
        snapshot = await _read_and_store(config_id)
    except BacnetReadError:
        return AutomationActionResult.failure(
            "The configured BACnet device did not answer the read-only refresh.",
            retryable=True,
        )
    return AutomationActionResult.success(
        {
            "status": "ok",
            "config_id": config_id,
            "reading_count": len(snapshot.readings),
        }
    )


automations.action("refresh", label="Refresh BACnet readings")(_refresh_device)
