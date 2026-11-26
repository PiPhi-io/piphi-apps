from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from copy import deepcopy
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    RuntimeConfigSnapshot,
    SQLiteAutomationIdempotencyStore,
    build_sync_response,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .bthome import UnsupportedAdvertisement, decode_service_data
from .contract import CAPABILITIES, COMMANDS
from .gateway import ConsumerMissing, GatewayClient, GatewayError, Observation, ObservationPage, SequenceGap
from .persistence import load_state, save_state
from .privacy import redact
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

starter = create_runtime_starter(integration_id=INTEGRATION_ID, integration_name=INTEGRATION_NAME, version=INTEGRATION_VERSION)
runtime, registry, telemetry, config_sync = starter.runtime, starter.registry, starter.telemetry_client, starter.config_sync
automations = AutomationRegistry(idempotency_store=SQLiteAutomationIdempotencyStore(os.getenv("PIPHI_AUTOMATION_LEDGER_PATH", "./data/automation-actions.sqlite3")))
for _event_type, _label in {
    "runtime.config.applied": "BLE monitor configuration applied",
    "runtime.dependency.lost": "BLE gateway dependency lost",
    "runtime.dependency.recovered": "BLE gateway dependency recovered",
}.items():
    automations.event(_event_type, label=_label)
capabilities, commands = CAPABILITIES, COMMANDS
logger = logging.getLogger(__name__)


@dataclass
class ConsumerState:
    cursor: int = 0
    receiver_healthy: bool = False
    last_live_at: float | None = None
    last_ingested_at: str | None = None
    last_observed_monotonic_ms: int | None = None
    packet_ids: deque[int] = field(default_factory=lambda: deque(maxlen=32))
    parser_errors: int = 0
    malformed_observations: int = 0
    duplicate_packets: int = 0
    gap_resyncs: int = 0
    poll_failures: int = 0
    availability_baseline: bool = False
    was_available: bool = False


_clients: dict[str, GatewayClient] = {}
_bind_keys: dict[str, str] = {}
_configs: dict[str, DeviceConfig] = {}
_consumer_state: dict[str, ConsumerState] = {}
_config_lock = asyncio.Lock()
_poll_lock = asyncio.Lock()
_persisted_state: dict[str, dict[str, Any]] = {}
state_loader = load_state
state_saver = save_state


def gateway_client(config: DeviceConfig) -> GatewayClient:
    return GatewayClient(str(config.gateway_url), config.gateway_token.get_secret_value())


def _gateway_consumer_id(config_id: str) -> str:
    return f"pbm-{hashlib.sha256(config_id.encode()).hexdigest()[:32]}"


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "gateway_url": str(config.gateway_url),
        "gateway_consumer_id": _gateway_consumer_id(identity["config_id"]),
        "device_handle": config.device_handle,
        "bind_key_configured": config.bind_key is not None,
        "alias": config.alias,
        "poll_interval_seconds": config.poll_interval_seconds,
        "stale_after_seconds": config.stale_after_seconds,
    }


def append_runtime_event(event_type: str, device: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = build_local_event_record(event_type=event_type, device=redact(device), payload=redact(payload or {}), source=INTEGRATION_ID, severity="info")
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def _reject_duplicate_target(entry: dict[str, Any]) -> None:
    for existing_id in registry.ids():
        existing = registry.get(existing_id)
        if existing is None or existing_id == entry["config_id"]:
            continue
        if (
            str(existing.get("gateway_url", "")).rstrip("/") == str(entry["gateway_url"]).rstrip("/")
            and existing.get("device_handle") == entry["device_handle"]
        ):
            raise HTTPException(
                status_code=409,
                detail=f"BLE device is already configured by config_id={existing_id}",
            )


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = entry["config_id"]
    async with _config_lock:
        _reject_duplicate_target(entry)
        candidate = gateway_client(config)
        bind_key = config.bind_key.get_secret_value() if config.bind_key else None
        temporary_id = f"{entry['gateway_consumer_id']}-probe"
        try:
            if bind_key:
                await candidate.register(temporary_id, config.device_handle, bind_key)
            else:
                await candidate.register(temporary_id, config.device_handle)
            await candidate.snapshot(temporary_id)
            await candidate.unregister(temporary_id)
            if bind_key:
                await candidate.register(entry["gateway_consumer_id"], config.device_handle, bind_key)
            else:
                await candidate.register(entry["gateway_consumer_id"], config.device_handle)
            snapshot = await candidate.snapshot(entry["gateway_consumer_id"])
        except Exception:
            try:
                await candidate.unregister(temporary_id)
            except Exception:
                pass
            await candidate.close()
            raise
        old_client = _clients.get(config_id)
        old_bind_key = _bind_keys.get(config_id)
        old_consumer_state = _consumer_state.get(config_id)
        old_config = _configs.get(config_id)
        old_entry = registry.get(config_id)
        old_state = deepcopy(registry.state_snapshots.get(config_id))
        _clients[config_id] = candidate
        if bind_key:
            _bind_keys[config_id] = bind_key
        else:
            _bind_keys.pop(config_id, None)
        _consumer_state[config_id] = ConsumerState()
        _configs[config_id] = config
        registry.set(config_id, entry)
        restored = _persisted_state.get(config_id)
        initial = deepcopy(restored.get("state", {})) if restored and restored.get("device_id") == entry["device_id"] else {}
        registry.update_state(config_id, {**initial, **_initial_public_state()}, device_id=entry["device_id"])
        try:
            await _apply_page(config_id, snapshot, snapshot=True)
            await persist_runtime_state()
        except Exception:
            if old_entry is None:
                registry.remove(config_id)
            else:
                registry.set(config_id, old_entry)
                if old_state is not None:
                    registry.state_snapshots[config_id] = old_state
            if old_client is None:
                _clients.pop(config_id, None)
            else:
                _clients[config_id] = old_client
            if old_bind_key is None:
                _bind_keys.pop(config_id, None)
            else:
                _bind_keys[config_id] = old_bind_key
            if old_consumer_state is None:
                _consumer_state.pop(config_id, None)
            else:
                _consumer_state[config_id] = old_consumer_state
            if old_config is None:
                _configs.pop(config_id, None)
            else:
                _configs[config_id] = old_config
            await candidate.close()
            raise
        if old_client is not None:
            await old_client.close()
        append_runtime_event("runtime.config.applied", entry, {"device_handle": config.device_handle})


async def remove_config(config_id: str) -> bool:
    client = _clients.pop(config_id, None)
    if client is not None:
        try:
            await client.unregister(entry["gateway_consumer_id"] if (entry := registry.get(config_id)) else _gateway_consumer_id(config_id))
        except GatewayError:
            logger.warning("Gateway consumer removal failed for %s", config_id)
        await client.close()
    _consumer_state.pop(config_id, None)
    _bind_keys.pop(config_id, None)
    _configs.pop(config_id, None)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    await persist_runtime_state()
    append_runtime_event("runtime.config.removed", entry, {"device_handle": entry.get("device_handle")})
    return True


async def apply_config_snapshot(snapshot: RuntimeConfigSnapshot, *, restored: bool = False):
    """Reconcile one Core generation and roll back all local/remote changes on failure."""
    async with _poll_lock:
        if config_sync.is_stale(snapshot):
            return config_sync.build_stale_response(snapshot=snapshot, active_config_ids=registry.ids())
        incoming = {
            str(config.config_id or config.id): config
            for config in snapshot.configs
        }
        if len(incoming) != len(snapshot.configs):
            raise ValueError("configuration snapshot contains duplicate config IDs")
        old_configs = dict(_configs)
        old_events = deepcopy(registry.recent_events)
        old_generation = config_sync.get_current_generation()
        try:
            for config in incoming.values():
                await apply_config(config)
            removed = [config_id for config_id in list(registry.ids()) if config_id not in incoming]
            for config_id in removed:
                await remove_config(config_id)
            generation = config_sync.mark_generation(snapshot.generation)
        except Exception:
            # Restore every previous registration using the Core-owned secrets
            # retained only in process memory. Then remove any newly introduced
            # consumer. Event history is restored so a failed generation emits
            # no partial lifecycle transitions.
            for config_id in list(_configs):
                if config_id not in old_configs:
                    await remove_config(config_id)
            for config in old_configs.values():
                await apply_config(config)
            registry.recent_events.clear()
            registry.recent_events.extend(old_events)
            runtime.process_state.current_generation = old_generation
            raise
        return build_sync_response(
            status="synced",
            container_id=snapshot.container_id,
            reason=snapshot.reason,
            generation=generation,
            applied=list(incoming),
            removed=removed,
            active_config_ids=registry.ids(),
            metadata={"atomic": True, "contract_version": 1},
        )


def _initial_public_state() -> dict[str, Any]:
    return {"receiver_healthy": False, "observation_fresh": False, "sensor_available": False, "measurement_age_seconds": None}


def _publish_state(entry: dict[str, Any], metrics: dict[str, Any]) -> None:
    config_id = entry["config_id"]
    previous = registry.state_snapshots.get(config_id, {}).get("state", {})
    latest = {**previous, **metrics}
    registry.update_state(config_id, latest, device_id=entry["device_id"])
    public = {key: value for key, value in latest.items() if key not in {"trigger_based", "packet_id"}}
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=config_id,
        device_id=entry["device_id"],
        container_id=entry.get("container_id"),
        metrics=public,
        units={"battery_percent": "%", "temperature_c": "°C", "humidity_percent": "%", "rssi_dbm": "dBm", "measurement_age_seconds": "s"},
    )


def _availability_transition(entry: dict[str, Any], status: ConsumerState, available: bool) -> None:
    if not status.availability_baseline:
        status.availability_baseline = True
        status.was_available = available
        return
    if available == status.was_available:
        return
    status.was_available = available
    append_runtime_event(
        "runtime.dependency.recovered" if available else "runtime.dependency.lost",
        entry,
        {"dependency": "piphi-ble-gateway-sidecar"},
    )


def _refresh_freshness(config_id: str, *, now: float | None = None) -> None:
    entry = registry.get(config_id)
    status = _consumer_state.get(config_id)
    if entry is None or status is None:
        return
    current = monotonic() if now is None else now
    age = None if status.last_live_at is None else max(0.0, current - status.last_live_at)
    fresh = age is not None and age <= entry["stale_after_seconds"]
    available = fresh and status.receiver_healthy
    _publish_state(entry, {
        "receiver_healthy": status.receiver_healthy,
        "observation_fresh": fresh,
        "sensor_available": available,
        "measurement_age_seconds": None if age is None else round(age, 1),
    })
    _availability_transition(entry, status, available)


def _process_observation(config_id: str, observation: Observation, *, live_allowed: bool, now: float) -> None:
    entry = registry.get(config_id)
    status = _consumer_state[config_id]
    if entry is None or observation.device_handle != entry["device_handle"]:
        return
    try:
        metrics = decode_service_data(observation.service_data)
    except (UnsupportedAdvertisement, ValueError):
        status.parser_errors += 1
        return
    if metrics is None:
        return
    status.last_ingested_at = observation.ingested_at
    status.last_observed_monotonic_ms = observation.observed_monotonic_ms
    if live_allowed and not observation.replayed:
        ingested = datetime.fromisoformat(observation.ingested_at.replace("Z", "+00:00"))
        ingress_age = max(0.0, (datetime.now(timezone.utc) - ingested).total_seconds())
        status.last_live_at = now - ingress_age
    packet_id = metrics.pop("packet_id", None)
    if packet_id is not None and packet_id in status.packet_ids:
        status.duplicate_packets += 1
        previous = registry.state_snapshots.get(config_id, {}).get("state", {})
        if previous.get("rssi_dbm") != observation.rssi:
            _publish_state(entry, {"rssi_dbm": observation.rssi, "last_measurement_at": observation.ingested_at})
        return
    if packet_id is not None:
        status.packet_ids.append(packet_id)
    state = {**metrics, "rssi_dbm": observation.rssi, "last_measurement_at": observation.ingested_at}
    _publish_state(entry, state)


async def _apply_page(config_id: str, page: ObservationPage, *, snapshot: bool = False, now: float | None = None) -> None:
    status = _consumer_state[config_id]
    status.receiver_healthy = page.receiver_healthy
    status.malformed_observations += page.malformed_count
    current = monotonic() if now is None else now
    for observation in page.observations:
        _process_observation(config_id, observation, live_allowed=not snapshot, now=current)
    status.cursor = max(status.cursor, page.cursor)
    _refresh_freshness(config_id, now=current)


async def poll_config(config_id: str, *, now: float | None = None) -> None:
    client = _clients.get(config_id)
    status = _consumer_state.get(config_id)
    if client is None or status is None:
        get_entry_or_404(config_id)
        raise GatewayError("BLE gateway client is not initialized")
    try:
        entry = get_entry_or_404(config_id)
        consumer_id = entry["gateway_consumer_id"]
        try:
            page = await client.observations(consumer_id, after=status.cursor)
        except ConsumerMissing:
            # A sidecar process restart intentionally forgets transient consumer
            # keys. Re-register from Core-owned configuration without resetting
            # last-good measurements.
            bind_key = _bind_keys.get(config_id)
            if bind_key:
                await client.register(consumer_id, entry["device_handle"], bind_key)
            else:
                await client.register(consumer_id, entry["device_handle"])
            page = await client.snapshot(consumer_id, after=status.cursor)
            await _apply_page(config_id, page, snapshot=True, now=now)
            return
        except SequenceGap:
            status.gap_resyncs += 1
            page = await client.snapshot(consumer_id, after=status.cursor)
            await _apply_page(config_id, page, snapshot=True, now=now)
            return
        if page.gap:
            status.gap_resyncs += 1
            page = await client.snapshot(consumer_id, after=status.cursor)
            await _apply_page(config_id, page, snapshot=True, now=now)
        else:
            await _apply_page(config_id, page, now=now)
    except GatewayError:
        status.receiver_healthy = False
        status.poll_failures += 1
        _refresh_freshness(config_id, now=now)
        raise


async def refresh_config(config_id: str) -> dict[str, Any]:
    await poll_config(config_id)
    return registry.state_snapshots.get(config_id, {}).get("state", {})


def _persistable_entries() -> dict[str, dict[str, Any]]:
    return {
        config_id: {
            "device_id": str(entry["device_id"]),
            "state": redact(deepcopy(registry.state_snapshots.get(config_id, {}).get("state", {}))),
        }
        for config_id in registry.ids()
        if (entry := registry.get(config_id)) is not None
    }


async def persist_runtime_state() -> None:
    records = _persistable_entries()
    await asyncio.to_thread(state_saver, records)
    _persisted_state.clear()
    _persisted_state.update(deepcopy(records))


async def restore_runtime_state() -> None:
    try:
        records = await asyncio.to_thread(state_loader)
    except (OSError, TypeError, ValueError):
        logger.exception("passive_ble_state_restore_failed")
        records = {}
    _persisted_state.clear()
    _persisted_state.update(records)


async def scan_poll_loop() -> None:
    backoff = 1.0
    while True:
        async with _poll_lock:
            failures = 0
            for config_id in list(registry.ids()):
                try:
                    await poll_config(config_id)
                    await persist_runtime_state()
                except Exception:
                    failures += 1
                    logger.warning("BLE gateway poll failed for %s", config_id)
        intervals = [entry["poll_interval_seconds"] for config_id in registry.ids() if (entry := registry.get(config_id)) is not None]
        delay = min(intervals, default=30)
        if failures:
            delay = min(delay, backoff)
            backoff = min(backoff * 2, 60)
        else:
            backoff = 1.0
        await asyncio.sleep(max(1.0, delay))


def diagnostic_snapshot() -> dict[str, Any]:
    return {
        config_id: {
            "device_handle": (entry or {}).get("device_handle"),
            "receiver_healthy": status.receiver_healthy,
            "cursor": status.cursor,
            "last_ingested_at": status.last_ingested_at,
            "parser_errors": status.parser_errors,
            "malformed_observations": status.malformed_observations,
            "duplicate_packets": status.duplicate_packets,
            "gap_resyncs": status.gap_resyncs,
            "poll_failures": status.poll_failures,
        }
        for config_id, status in _consumer_state.items()
        if (entry := registry.get(config_id)) is not None
    }


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            config_id = str(request.config_id or target.get("config_id") or "")
            entry = get_entry_or_404(config_id)
            event = append_runtime_event("runtime.command.received", entry, {"command": _command_name})
            return {"event": event, "command": _command_name, "device_id": entry["device_id"], "config_id": config_id, "target": target, "params": request.args}
        automations.action(command_name, label=str(command_definition.get("description") or command_name))(handler)


_register_automation_actions()


async def _refresh_all_state() -> None:
    for config_id in registry.ids():
        await refresh_config(config_id)


starter.state.provide(_refresh_all_state, source=INTEGRATION_ID)
