from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    CoreDeliveryError,
    CoreSourceUnavailableError,
    SourceBinding,
    SourceTelemetryClient,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .detector import apply_points
from .persistence import CycleState, CycleStore
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID, integration_name=INTEGRATION_NAME, version=INTEGRATION_VERSION
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
source_client = SourceTelemetryClient(process_state=runtime.process_state)
store = CycleStore(os.getenv("PIPHI_WASHDATA_STATE_PATH", "./data/washdata-state.sqlite3"))
automations = AutomationRegistry(
    idempotency_store=SQLiteAutomationIdempotencyStore(
        os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")
    )
)
capabilities = CAPABILITIES
commands = COMMANDS


@dataclass(slots=True)
class RuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    next_poll_at: dict[str, float] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


runtime_data = RuntimeData()


def append_runtime_event(
    event_type: str, entry: dict[str, Any], payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=entry,
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


def _config_id(config: DeviceConfig) -> str:
    return str(config.config_id or config.id)


def _select_binding(bindings: list[SourceBinding], binding_key: str) -> SourceBinding:
    matches = [binding for binding in bindings if binding.binding_key == binding_key]
    if not matches:
        raise HTTPException(
            status_code=422, detail={"error": "source_binding_missing", "binding_key": binding_key}
        )
    if len(matches) != 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "source_binding_ambiguous", "binding_key": binding_key},
        )
    return matches[0]


def _make_entry(config: DeviceConfig, binding: SourceBinding) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    config_id = _config_id(config)
    return {
        **identity,
        "config_id": config_id,
        "device_id": f"{INTEGRATION_ID}:{config_id}",
        "alias": config.alias,
        "binding_id": binding.binding_id,
        "binding_key": binding.binding_key,
        "canonical_device_id": binding.canonical_device_id,
        "config": {
            "id": config.id,
            "config_id": config_id,
            "container_id": config.container_id,
            "alias": config.alias,
            "binding_key": config.binding_key,
            "power_metric": config.power_metric,
            "start_threshold_w": config.start_threshold_w,
            "stop_threshold_w": config.stop_threshold_w,
            "start_debounce_samples": config.start_debounce_samples,
            "stop_debounce_samples": config.stop_debounce_samples,
            "poll_interval_seconds": config.poll_interval_seconds,
            "page_size": config.page_size,
        },
    }


def _publish_state(entry: dict[str, Any], state: CycleState) -> dict[str, Any]:
    public = state.public()
    registry.update_state(state.config_id, public, device_id=entry["device_id"])
    metrics = {key: value for key, value in public.items() if value is not None}
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=state.config_id,
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={
            "power_w": "W",
            "peak_power_w": "W",
            "cycle_energy_kwh": "kWh",
            "cycle_duration_s": "s",
        },
    )
    return public


async def apply_config(config: DeviceConfig) -> None:
    config_id = _config_id(config)
    bindings = await source_client.list_bindings(
        consumer_config_id=config_id,
        auth_context=runtime.auth,
        container_id=config.container_id,
    )
    binding = _select_binding(bindings, config.binding_key)
    entry = _make_entry(config, binding)
    async with runtime_data.config_lock:
        existing = store.load(config_id)
        if existing is not None and existing.binding_id != binding.binding_id:
            store.delete(config_id)
            existing = None
        state = existing or CycleState(
            config_id=config_id,
            binding_id=binding.binding_id,
            binding_key=binding.binding_key,
            canonical_device_id=binding.canonical_device_id,
        )
        if binding.source_status != "active":
            state.stale = True
            state.detector_status = "unavailable"
            state.source_error = "source_unavailable"
        store.save(state)
        runtime_data.configs[config_id] = config
        runtime_data.locks.setdefault(config_id, asyncio.Lock())
        runtime_data.next_poll_at[config_id] = 0
        registry.set(config_id, entry)
        _publish_state(entry, state)
    append_runtime_event("runtime.config.applied", entry, {"binding_key": binding.binding_key})


async def remove_config(config_id: str) -> bool:
    async with runtime_data.config_lock:
        runtime_data.configs.pop(config_id, None)
        runtime_data.locks.pop(config_id, None)
        runtime_data.next_poll_at.pop(config_id, None)
        entry = registry.remove(config_id)
        store.delete(config_id)
    if entry is not None:
        append_runtime_event("runtime.config.removed", entry)
    return entry is not None


def _mark_failure(
    config_id: str, entry: dict[str, Any], state: CycleState, status: str, error: str
) -> dict[str, Any]:
    previous = state.detector_status
    state.stale = True
    state.detector_status = status
    state.source_error = error
    store.save(state)
    public = _publish_state(entry, state)
    if previous != status:
        append_runtime_event("detector.degraded", entry, {"status": status, "error": error})
    return public


async def refresh_config(config_id: str) -> dict[str, Any]:
    entry = get_entry_or_404(config_id)
    config = runtime_data.configs.get(config_id)
    if config is None:
        raise HTTPException(status_code=409, detail={"error": "configuration_unavailable"})
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        current = store.load(config_id)
        if current is None:
            raise HTTPException(status_code=409, detail={"error": "durable_state_missing"})
        try:
            page = await source_client.read_telemetry(
                binding_id=current.binding_id,
                cursor=current.next_cursor,
                limit=config.page_size,
                auth_context=runtime.auth,
                container_id=config.container_id,
            )
        except CoreSourceUnavailableError:
            state = _mark_failure(config_id, entry, current, "unavailable", "source_unavailable")
            return {**state, "has_more": False}
        except CoreDeliveryError as exc:
            state = _mark_failure(config_id, entry, current, "degraded", type(exc).__name__)
            return {**state, "has_more": False}

        known = store.processed_ids(config_id, (point.event_id for point in page.points))
        updated, accepted_ids, domain_events = apply_points(
            current, page.points, config, already_processed=known
        )
        prior_status = current.detector_status
        updated.stale = page.stale
        updated.detector_status = "stale" if page.stale else "healthy"
        updated.source_error = None
        store.commit_page(updated, accepted_ids, page.next_cursor)
        public = _publish_state(entry, updated)
        if prior_status != "healthy" and updated.detector_status == "healthy":
            append_runtime_event("detector.recovered", entry)
        elif prior_status != "stale" and updated.detector_status == "stale":
            append_runtime_event("detector.degraded", entry, {"status": "stale"})
        for event_type, payload in domain_events:
            append_runtime_event(event_type, entry, payload)
        runtime_data.next_poll_at[config_id] = time.monotonic() + config.poll_interval_seconds
        return {**public, "has_more": page.has_more, "processed_event_count": len(accepted_ids)}


async def poll_sources() -> None:
    while True:
        await asyncio.sleep(0.25)
        now = time.monotonic()
        due = [
            config_id
            for config_id in registry.ids()
            if runtime_data.next_poll_at.get(config_id, 0) <= now
        ]
        if due:
            results = await asyncio.gather(
                *(refresh_config(config_id) for config_id in due), return_exceptions=True
            )
            for config_id, result in zip(due, results, strict=True):
                if isinstance(result, Exception):
                    config = runtime_data.configs.get(config_id)
                    runtime_data.next_poll_at[config_id] = now + (
                        config.poll_interval_seconds if config else 5
                    )


def _register_actions() -> None:
    async def refresh_handler(request):
        target = request.target if isinstance(request.target, dict) else {}
        config_id = str(request.config_id or target.get("config_id") or "")
        if not config_id:
            raise HTTPException(status_code=422, detail={"error": "config_id_required"})
        return {
            "command": "refresh",
            "config_id": config_id,
            "state": await refresh_config(config_id),
        }

    automations.action("refresh", label=str(COMMANDS["refresh"]["description"]))(refresh_handler)


_register_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await refresh_config(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
