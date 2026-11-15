from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections.abc import Callable
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
from .composite_model import normalize_composites
from .modbus_tcp import ModbusTCPClient, read_holding_register
from .modbus_model import entity_response, normalize_snapshot
from .profile_codec import profile_hash
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .sidecar_client import ModbusSidecarClient, SidecarError

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
point_models: dict[str, list[dict[str, Any]]] = {}
composite_models: dict[str, list[dict[str, Any]]] = {}
sidecar_clients: dict[str, ModbusSidecarClient] = {}
sidecar_replay: dict[str, dict[str, Any]] = {}
sidecar_client_factory: Callable[[], ModbusSidecarClient] = ModbusSidecarClient
tcp_clients: dict[str, ModbusTCPClient] = {}
tcp_client_factory: Callable[..., ModbusTCPClient] = ModbusTCPClient


def configured_poll_groups(config: DeviceConfig) -> list[dict[str, Any]]:
    assigned = {
        point_id for group in config.poll_groups for point_id in group.point_ids
    }
    groups = [
        {
            "id": group.id,
            "point_ids": list(group.point_ids),
            "interval_seconds": group.interval_seconds,
            "priority": group.priority,
        }
        for group in config.poll_groups
    ]
    remaining = [point.id for point in config.points if point.id not in assigned]
    if remaining or not config.points:
        groups.append(
            {
                "id": "default",
                "point_ids": remaining,
                "interval_seconds": (
                    config.poll_interval_seconds
                    if config.poll_interval_seconds is not None
                    else (15 if config.points else 300)
                ),
                "priority": 0,
            }
        )
    return groups


def _jittered_delay(config: DeviceConfig, delay: float) -> float:
    spread = delay * config.poll_jitter_percent / 100
    return max(0.1, delay + random.uniform(-spread, spread))


def initialize_poll_schedule(
    entry: dict[str, Any], config: DeviceConfig, *, now: float | None = None
) -> None:
    current = time.monotonic() if now is None else now
    entry["poll_schedule"] = {
        group["id"]: {
            **group,
            "next_poll_at": (
                None
                if group["interval_seconds"] == 0
                else current + _jittered_delay(config, group["interval_seconds"])
            ),
            "consecutive_failures": 0,
        }
        for group in configured_poll_groups(config)
    }


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"api_key"}),
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


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = str(entry["config_id"])
    previous_tcp = tcp_clients.pop(config_id, None)
    if previous_tcp is not None:
        await previous_tcp.close()
    sidecar_clients.pop(config_id, None)
    sidecar_replay.pop(config_id, None)
    registry.set(config_id, entry)
    if config.transport in {"rtu_sidecar", "ascii_sidecar"}:
        client = sidecar_client_factory()
        sidecar_payload = sidecar_config_payload(config)
        sidecar_clients[config_id] = client
        try:
            await client.configure(sidecar_payload)
            snapshot = await client.snapshot(config_id)
            await sync_sidecar_entry(entry, client)
            sidecar_replay[config_id] = {
                "cursor": int(snapshot.get("latest_sequence") or 0),
                "stream_id": str(snapshot.get("stream_id") or ""),
                "dropped": int(snapshot.get("dropped_event_count") or 0),
            }
        except (SidecarError, TypeError, ValueError) as exc:
            registry.update_state(
                config_id,
                {
                    "connected": False,
                    "transport": config.transport,
                    "quality": "unavailable",
                    "last_error_code": type(exc).__name__,
                    "config_id": config_id,
                },
                device_id=entry["device_id"],
            )
        append_runtime_event(
            "runtime.config.applied",
            entry,
            {"transport": config.transport, "alias": config.alias},
        )
        initialize_poll_schedule(entry, config)
        return
    if config.points:
        client = tcp_client_factory(
            config.host,
            timeout=config.response_timeout_seconds,
            inter_message_delay_ms=config.inter_message_delay_ms,
            transport=config.transport,
            tls_ca_certificate=config.tls_ca_certificate,
            tls_server_name=config.tls_server_name,
        )
        tcp_clients[config_id] = client
        await sync_tcp_entry(entry, client)
        append_runtime_event(
            "runtime.config.applied",
            entry,
            {
                "transport": config.transport,
                "profile_id": config.profile_id,
                "alias": config.alias,
            },
        )
        initialize_poll_schedule(entry, config)
        return
    registry.update_state(
        config_id,
        {
            "connected": False,
            "host": config.host,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    if config.register_address is not None:
        await refresh_entry(entry)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )
    initialize_poll_schedule(entry, config)


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config = DeviceConfig.model_validate(entry["config"])
    if config.transport in {"rtu_sidecar", "ascii_sidecar"}:
        client = sidecar_clients.get(str(entry["config_id"]))
        if client is None:
            client = sidecar_client_factory()
            sidecar_clients[str(entry["config_id"])] = client
        try:
            await replay_sidecar_events(entry, client)
            await client.refresh(str(entry["config_id"]))
            return await sync_sidecar_entry(entry, client)
        except (SidecarError, TypeError, ValueError) as exc:
            try:
                await client.configure(sidecar_config_payload(config))
                snapshot = await client.snapshot(str(entry["config_id"]))
                recovered_state = await sync_sidecar_entry(entry, client)
                sidecar_replay[str(entry["config_id"])] = {
                    "cursor": int(snapshot.get("latest_sequence") or 0),
                    "stream_id": str(snapshot.get("stream_id") or ""),
                    "dropped": int(snapshot.get("dropped_event_count") or 0),
                }
                append_runtime_event(
                    "modbus.sidecar.recovered",
                    entry,
                    {"reason": "configuration_reapplied"},
                )
                return recovered_state
            except (SidecarError, TypeError, ValueError):
                pass
            state = {
                "connected": False,
                "transport": config.transport,
                "quality": "unavailable",
                "last_error_code": type(exc).__name__,
            }
            registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
            return state
    if config.points:
        config_id = str(entry["config_id"])
        client = tcp_clients.get(config_id)
        if client is None:
            client = tcp_client_factory(
                config.host,
                timeout=config.response_timeout_seconds,
                inter_message_delay_ms=config.inter_message_delay_ms,
                transport=config.transport,
                tls_ca_certificate=config.tls_ca_certificate,
                tls_server_name=config.tls_server_name,
            )
            tcp_clients[config_id] = client
        return await sync_tcp_entry(entry, client)
    if config.register_address is None:
        state = {"connected": False, "reason": "register_address_missing"}
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state
    try:
        reading = await read_holding_register(
            config.host,
            config.register_address,
            config.unit_id if config.unit_id is not None else 1,
        )
    except (TimeoutError, OSError, ValueError, EOFError) as exc:
        logger.warning(
            "modbus_register_read_failed config_id=%s error=%s",
            entry["config_id"],
            type(exc).__name__,
        )
        state = {"connected": False, "reason": "register_read_failed"}
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state
    metrics = {"connected": True, "holding_register_value": reading.value}
    registry.update_state(entry["config_id"], metrics, device_id=entry["device_id"])
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: (
                completed.exception() if not completed.cancelled() else None
            )
        )
    return metrics


async def poll_registers() -> None:
    while True:
        await asyncio.sleep(1)
        await poll_due_groups()


async def poll_due_groups(*, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    due: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for entry in list(registry.entries.values()):
        config = DeviceConfig.model_validate(entry["config"])
        if "poll_schedule" not in entry:
            initialize_poll_schedule(entry, config, now=current)
        for group in entry["poll_schedule"].values():
            next_poll_at = group.get("next_poll_at")
            if next_poll_at is not None and next_poll_at <= current:
                due.append((-int(group["priority"]), entry, group))
    for _, entry, group in sorted(
        due, key=lambda item: (item[0], str(item[1]["config_id"]), item[2]["id"])
    ):
        await poll_group(entry, group, now=current)


async def poll_group(
    entry: dict[str, Any], group: dict[str, Any], *, now: float | None = None
) -> dict[str, Any]:
    config = DeviceConfig.model_validate(entry["config"])
    config_id = str(entry["config_id"])
    current = time.monotonic() if now is None else now
    try:
        if config.transport in {"rtu_sidecar", "ascii_sidecar"}:
            client = sidecar_clients.get(config_id)
            if client is None:
                raise ValueError("sidecar_not_configured")
            point_ids = list(group["point_ids"])
            if point_ids and len(point_ids) != len(config.points):
                for index, point_id in enumerate(point_ids):
                    if index and config.inter_message_delay_ms:
                        await asyncio.sleep(config.inter_message_delay_ms / 1000)
                    await client.refresh(config_id, point_id)
            else:
                await client.refresh(config_id)
            state = await sync_sidecar_entry(
                entry,
                client,
                polled_point_ids=set(point_ids) if point_ids else None,
            )
        elif config.points:
            client = tcp_clients.get(config_id)
            if client is None:
                raise ValueError("tcp_profile_not_configured")
            selected_ids = set(group["point_ids"])
            selected = [point for point in config.points if point.id in selected_ids]
            state = await sync_tcp_entry(entry, client, points=selected)
        else:
            state = await refresh_entry(entry)
    except (SidecarError, TimeoutError, OSError, ValueError) as exc:
        logger.warning(
            "modbus_poll_group_failed config_id=%s group_id=%s error=%s",
            config_id,
            group["id"],
            type(exc).__name__,
        )
        models = point_models.get(config_id, [])
        selected_ids = set(group["point_ids"])
        for model in models:
            if not selected_ids or model["point_id"] in selected_ids:
                model["state"]["quality"] = (
                    "stale"
                    if model["state"].get("point_value") is not None
                    else "unavailable"
                )
                model["state"]["error_code"] = type(exc).__name__
        quality_counts = _quality_counts(models)
        state = {
            "connected": quality_counts["good"] > 0,
            "transport": config.transport,
            "last_error_code": type(exc).__name__,
        }
        _record_poll_result(
            entry,
            state,
            request_success_count=0,
            request_failure_count=max(1, len(selected_ids)),
            duration_ms=0,
            quality_counts=quality_counts,
        )
        registry.update_state(config_id, state, device_id=entry["device_id"])
    failed = state.get("poll_outcome") == "failed"
    group["consecutive_failures"] = (
        int(group.get("consecutive_failures", 0)) + 1 if failed else 0
    )
    base = max(1, int(group["interval_seconds"]))
    delay = min(
        config.poll_backoff_max_seconds,
        base * (2 ** int(group["consecutive_failures"])),
    )
    group["next_poll_at"] = current + _jittered_delay(config, delay)
    return state


async def remove_config(config_id: str) -> bool:
    point_models.pop(config_id, None)
    composite_models.pop(config_id, None)
    sidecar_clients.pop(config_id, None)
    sidecar_replay.pop(config_id, None)
    tcp_client = tcp_clients.pop(config_id, None)
    if tcp_client is not None:
        await tcp_client.close()
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


def _quality_counts(models: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"good": 0, "stale": 0, "unavailable": 0}
    for model in models:
        quality = str(model.get("state", {}).get("quality") or "unavailable")
        counts[quality if quality in counts else "unavailable"] += 1
    return counts


def _record_poll_result(
    entry: dict[str, Any],
    state: dict[str, Any],
    *,
    request_success_count: int,
    request_failure_count: int,
    duration_ms: float,
    quality_counts: dict[str, int],
) -> None:
    if request_success_count and request_failure_count:
        outcome = "partial"
    elif request_success_count:
        outcome = "success"
    else:
        outcome = "failed"
    metrics = entry.setdefault(
        "poll_metrics",
        {
            "poll_success_count": 0,
            "poll_partial_failure_count": 0,
            "poll_failure_count": 0,
            "consecutive_failure_count": 0,
        },
    )
    counter = {
        "success": "poll_success_count",
        "partial": "poll_partial_failure_count",
        "failed": "poll_failure_count",
    }[outcome]
    metrics[counter] = int(metrics[counter]) + 1
    metrics["consecutive_failure_count"] = (
        int(metrics["consecutive_failure_count"]) + 1
        if outcome == "failed"
        else 0
    )
    metrics.update(
        last_poll_at=datetime.now(UTC).isoformat(),
        last_poll_duration_ms=round(duration_ms, 3),
        last_poll_outcome=outcome,
    )
    stale_count = quality_counts["stale"] + quality_counts["unavailable"]
    state.update(
        **metrics,
        poll_outcome=outcome,
        stale_point_count=stale_count,
        point_quality_counts=quality_counts,
        quality=(
            "unavailable"
            if not state.get("connected")
            else "degraded"
            if outcome != "success" or stale_count
            else "good"
        ),
    )
    health = (
        "offline"
        if not state.get("connected")
        else "degraded"
        if state["quality"] == "degraded"
        else "healthy"
    )
    previous_health = entry.get("poll_health")
    previous_stale = int(entry.get("stale_point_count", 0))
    if previous_health is None:
        append_runtime_event(
            "device.online" if health != "offline" else "device.offline",
            entry,
            {"transport": state.get("transport")},
        )
        if health == "degraded":
            append_runtime_event(
                "transport.degraded", entry, {"poll_outcome": outcome}
            )
    elif health != previous_health:
        if health == "offline":
            append_runtime_event("device.offline", entry, {"poll_outcome": outcome})
        elif previous_health == "offline":
            append_runtime_event("device.online", entry, {"poll_outcome": outcome})
        if health == "degraded":
            append_runtime_event(
                "transport.degraded", entry, {"poll_outcome": outcome}
            )
        elif health == "healthy" and previous_health != "healthy":
            append_runtime_event(
                "transport.recovered", entry, {"poll_outcome": outcome}
            )
    if stale_count and not previous_stale:
        append_runtime_event(
            "points.stale", entry, {"stale_point_count": stale_count}
        )
    elif not stale_count and previous_stale:
        append_runtime_event("points.recovered", entry, {})
    entry["poll_health"] = health
    entry["stale_point_count"] = stale_count


async def sync_tcp_entry(
    entry: dict[str, Any],
    client: ModbusTCPClient,
    *,
    points: list[Any] | None = None,
) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    config = DeviceConfig.model_validate(entry["config"])
    selected_points = config.points if points is None else points
    snapshot = await client.snapshot(selected_points)
    snapshot.update(
        profile_id=config.profile_id,
        profile_version=config.profile_version,
        profile_hash=profile_hash(
            profile_id=config.profile_id,
            profile_version=config.profile_version,
            profile_provenance=config.profile_provenance,
            points=config.points,
            semantic_bindings={
                "composites": [
                    item.model_dump(mode="json") for item in config.composites
                ],
                "coil_commands": [
                    item.model_dump(mode="json") for item in config.coil_commands
                ],
            },
        ),
    )
    refreshed_models = normalize_snapshot(snapshot, config_id=config_id)
    if points is None or config_id not in point_models:
        models = refreshed_models
    else:
        refreshed_by_id = {
            str(model["point_id"]): model for model in refreshed_models
        }
        models = [
            refreshed_by_id.get(str(model["point_id"]), model)
            for model in point_models[config_id]
        ]
    point_models[config_id] = models
    composite_models[config_id] = normalize_composites(
        config.composites, models, config_id=config_id
    )
    quality_counts = _quality_counts(models)
    unit_health = snapshot.get("unit_health", [])
    state = {
        "connected": quality_counts["good"] > 0,
        "transport": config.transport,
        "quality": "good" if snapshot.get("connected") else "unavailable",
        "profile_id": snapshot["profile_id"],
        "profile_version": snapshot["profile_version"],
        "profile_hash": snapshot["profile_hash"],
        "responsive_unit_ids": [
            item["unit_id"]
            for item in unit_health
            if item.get("last_success_at")
            and int(item.get("consecutive_error_count") or 0) == 0
        ],
        "request_count": snapshot.get("request_count", 0),
        "unit_health": unit_health,
        "poll_duration_ms": snapshot.get("poll_duration_ms", 0),
        "retry_count": snapshot.get("retry_count", 0),
        "timeout_count": snapshot.get("timeout_count", 0),
        "transport_error_count": snapshot.get("error_count", 0),
        "reconnect_count": snapshot.get("reconnect_count", 0),
        "poll_group_count": len(configured_poll_groups(config)),
        "polling_enabled": any(
            group["interval_seconds"] > 0 for group in configured_poll_groups(config)
        ),
        "points": {model["point_id"]: model["state"] for model in models},
        "composites": {
            model["composite_id"]: model["state"]
            for model in composite_models[config_id]
        },
        "config_id": config_id,
        "last_error_code": snapshot.get("last_error_code"),
    }
    _record_poll_result(
        entry,
        state,
        request_success_count=int(snapshot.get("request_success_count") or 0),
        request_failure_count=int(snapshot.get("request_failure_count") or 0),
        duration_ms=float(snapshot.get("poll_duration_ms") or 0),
        quality_counts=quality_counts,
    )
    registry.update_state(config_id, state, device_id=entry["device_id"])
    return state


async def sync_sidecar_entry(
    entry: dict[str, Any],
    client: ModbusSidecarClient,
    *,
    polled_point_ids: set[str] | None = None,
) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    snapshot = await client.snapshot(config_id)
    models = normalize_snapshot(snapshot, config_id=config_id)
    point_models[config_id] = models
    config = DeviceConfig.model_validate(entry["config"])
    composite_models[config_id] = normalize_composites(
        config.composites, models, config_id=config_id
    )
    quality_counts = _quality_counts(models)
    polled_models = (
        models
        if polled_point_ids is None
        else [model for model in models if model["point_id"] in polled_point_ids]
    )
    polled_quality_counts = _quality_counts(polled_models)
    state = {
        "connected": bool(snapshot.get("connected")),
        "transport": config.transport,
        "quality": "good" if snapshot.get("connected") else "unavailable",
        "profile_id": snapshot.get("profile_id"),
        "profile_version": snapshot.get("profile_version"),
        "profile_hash": profile_hash(
            profile_id=config.profile_id,
            profile_version=config.profile_version,
            profile_provenance=config.profile_provenance,
            points=config.points,
            semantic_bindings={
                "composites": [
                    item.model_dump(mode="json") for item in config.composites
                ],
                "coil_commands": [
                    item.model_dump(mode="json") for item in config.coil_commands
                ],
            },
        ),
        "transport_profile_hash": snapshot.get("profile_hash"),
        "port_open": snapshot.get("port_open"),
        "responsive_unit_ids": snapshot.get("responsive_unit_ids", []),
        "queue_depth": snapshot.get("queue_depth"),
        "queue_capacity": snapshot.get("queue_capacity"),
        "queue_high_water_mark": snapshot.get("queue_high_water_mark"),
        "unit_health": snapshot.get("unit_health", []),
        "reconnect_count": snapshot.get("reconnect_count", 0),
        "timeout_count": snapshot.get("timeout_count", 0),
        "crc_error_count": snapshot.get("crc_error_count", 0),
        "lrc_error_count": snapshot.get("lrc_error_count", 0),
        "transport_error_count": snapshot.get("transport_error_count", 0),
        "poll_group_count": len(configured_poll_groups(config)),
        "polling_enabled": any(
            group["interval_seconds"] > 0 for group in configured_poll_groups(config)
        ),
        "points": {model["point_id"]: model["state"] for model in models},
        "composites": {
            model["composite_id"]: model["state"]
            for model in composite_models[config_id]
        },
        "config_id": config_id,
        "last_error_code": snapshot.get("last_error_code"),
    }
    _record_poll_result(
        entry,
        state,
        request_success_count=polled_quality_counts["good"],
        request_failure_count=(
            polled_quality_counts["stale"] + polled_quality_counts["unavailable"]
        ),
        duration_ms=float(snapshot.get("poll_duration_ms") or 0),
        quality_counts=quality_counts,
    )
    registry.update_state(config_id, state, device_id=entry["device_id"])
    return state


def sidecar_config_payload(config: DeviceConfig) -> dict[str, Any]:
    payload = config.model_dump(
        exclude={
            "api_key",
            "base_url",
            "composites",
            "coil_commands",
            "poll_groups",
            "poll_interval_seconds",
            "inter_message_delay_ms",
            "poll_jitter_percent",
            "poll_backoff_max_seconds",
        }
    )
    payload["registers"] = payload.pop("points")
    payload["host"] = "modbus-rtu-sidecar"
    payload["serial_mode"] = "ascii" if config.transport == "ascii_sidecar" else "rtu"
    payload.pop("transport", None)
    payload.pop("tls_ca_certificate", None)
    payload.pop("tls_server_name", None)
    return payload


async def replay_sidecar_events(
    entry: dict[str, Any], client: ModbusSidecarClient
) -> None:
    config_id = str(entry["config_id"])
    position = sidecar_replay.setdefault(
        config_id, {"cursor": 0, "stream_id": "", "dropped": 0}
    )
    replay = await client.events(config_id, after=int(position["cursor"]))
    stream_id = str(replay.get("stream_id") or "")
    dropped = int(replay.get("dropped") or 0)
    restarted = bool(position["stream_id"] and stream_id != position["stream_id"])
    gap = bool(replay.get("gap")) or dropped < int(position["dropped"])
    if restarted or gap:
        snapshot = await sync_sidecar_entry(entry, client)
        position.update(
            cursor=int(snapshot.get("latest_sequence") or 0),
            stream_id=str(snapshot.get("stream_id") or stream_id),
            dropped=int(snapshot.get("dropped_event_count") or 0),
        )
        append_runtime_event(
            "modbus.events.resynchronized",
            entry,
            {"reason": "sidecar_restart" if restarted else "replay_gap"},
        )
        return
    for event in replay.get("events", []):
        if not isinstance(event, dict):
            continue
        append_runtime_event(
            str(event.get("event_type") or "modbus.event"),
            entry,
            {
                "sequence": event.get("sequence"),
                "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
            },
        )
    position.update(
        cursor=int(replay.get("next_cursor") or position["cursor"]),
        stream_id=stream_id or position["stream_id"],
        dropped=dropped,
    )


def all_entities() -> list[dict[str, Any]]:
    return [
        entity_response(model)
        for config_id in sorted(set(point_models) | set(composite_models))
        for model in [
            *point_models.get(config_id, []),
            *composite_models.get(config_id, []),
        ]
    ]


def polling_diagnostics() -> dict[str, Any]:
    now = time.monotonic()
    diagnostics: dict[str, Any] = {}
    for config_id in registry.ids():
        entry = registry.get(config_id)
        if entry is None:
            continue
        config = DeviceConfig.model_validate(entry["config"])
        schedule = entry.get("poll_schedule", {})
        diagnostics[config_id] = {
            "transport": config.transport,
            "profile_id": config.profile_id,
            "poll_health": entry.get("poll_health", "unknown"),
            "metrics": dict(entry.get("poll_metrics", {})),
            "stale_point_count": int(entry.get("stale_point_count", 0)),
            "groups": [
                {
                    "id": group["id"],
                    "point_count": len(group["point_ids"]),
                    "interval_seconds": group["interval_seconds"],
                    "priority": group["priority"],
                    "enabled": group["next_poll_at"] is not None,
                    "next_poll_in_seconds": (
                        None
                        if group["next_poll_at"] is None
                        else round(max(0, group["next_poll_at"] - now), 3)
                    ),
                    "consecutive_failures": group["consecutive_failures"],
                }
                for group in sorted(schedule.values(), key=lambda item: item["id"])
            ],
        }
    return diagnostics


def find_point_model(config_id: str, device_id: str) -> dict[str, Any]:
    model = next(
        (
            item
            for item in point_models.get(config_id, [])
            if item["device_id"] == device_id
        ),
        None,
    )
    if model is None:
        raise ValueError("unknown_modbus_point")
    return model


def find_composite(config_id: str, device_id: str, config: DeviceConfig):
    composite_id = device_id.removeprefix(f"{config_id}:")
    return next(
        (item for item in config.composites if item.id == composite_id),
        None,
    )


def composite_command_value(composite, command: str, args: dict[str, Any]):
    binding = composite.commands.get(command)
    if binding is None:
        raise ValueError("unsupported_composite_command")
    if binding.argument is None:
        return binding.point_id, binding.value
    if binding.argument not in args:
        raise ValueError(f"{binding.argument}_required")
    return binding.point_id, args[binding.argument]


def resolve_coil_command(config: DeviceConfig, args: dict[str, Any]):
    command_id = str(args.get("command_id") or "").strip()
    if not command_id:
        raise ValueError("command_id_required")
    command = next(
        (candidate for candidate in config.coil_commands if candidate.id == command_id),
        None,
    )
    if command is None:
        raise ValueError("unknown_coil_command")
    point_by_id = {point.id: point for point in config.points}
    return command, [point_by_id[point_id] for point_id in command.point_ids]


async def execute_sidecar_command(
    *, config_id: str, device_id: str, command: str, args: dict[str, Any]
) -> dict[str, Any]:
    client = sidecar_clients.get(config_id)
    entry = registry.get(config_id)
    if client is None or entry is None:
        raise ValueError("sidecar_not_configured")
    config = DeviceConfig.model_validate(entry["config"])
    if command == "run_coil_command":
        binding, _ = resolve_coil_command(config, args)
        result = await client.write_coils(
            config_id, binding.point_ids, binding.values
        )
        if binding.pulse_seconds is not None:
            try:
                await asyncio.sleep(binding.pulse_seconds)
            finally:
                result = await client.write_coils(
                    config_id, binding.point_ids, binding.reset_values or []
                )
        await sync_sidecar_entry(entry, client)
        append_runtime_event(
            "modbus.coil_command.executed",
            entry,
            {
                "command_id": binding.id,
                "idempotency": binding.idempotency,
                "pulse": binding.pulse_seconds is not None,
            },
        )
        return {"ok": True, "command_id": binding.id, "result": result}
    composite = find_composite(config_id, device_id, config)
    if composite is not None:
        if command == "refresh":
            result = await client.refresh(config_id)
        else:
            point_id, value = composite_command_value(composite, command, args)
            result = await client.write(config_id, point_id, value)
        await sync_sidecar_entry(entry, client)
        return {
            "ok": True,
            "composite_id": composite.id,
            "result": result,
        }
    model = find_point_model(config_id, device_id)
    if command == "refresh":
        result = await client.refresh(config_id, str(model["point_id"]))
    elif command == "set_value":
        if "value" not in args:
            raise ValueError("value_required")
        result = await client.write(config_id, str(model["point_id"]), args["value"])
    else:
        raise ValueError("unsupported_modbus_command")
    await sync_sidecar_entry(entry, client)
    return result


async def execute_tcp_command(
    *, config_id: str, device_id: str, command: str, args: dict[str, Any]
) -> dict[str, Any]:
    client = tcp_clients.get(config_id)
    entry = registry.get(config_id)
    if client is None or entry is None:
        raise ValueError("tcp_profile_not_configured")
    config = DeviceConfig.model_validate(entry["config"])
    if command == "run_coil_command":
        binding, points = resolve_coil_command(config, args)
        values = await client.write_coils(points, binding.values)
        if binding.pulse_seconds is not None:
            try:
                await asyncio.sleep(binding.pulse_seconds)
            finally:
                values = await client.write_coils(points, binding.reset_values or [])
        await sync_tcp_entry(entry, client)
        append_runtime_event(
            "modbus.coil_command.executed",
            entry,
            {
                "command_id": binding.id,
                "idempotency": binding.idempotency,
                "pulse": binding.pulse_seconds is not None,
            },
        )
        return {"ok": True, "command_id": binding.id, "values": values}
    composite = find_composite(config_id, device_id, config)
    if composite is not None:
        if command == "refresh":
            await sync_tcp_entry(entry, client)
            return {"ok": True, "composite_id": composite.id}
        point_id, requested_value = composite_command_value(composite, command, args)
        point = next(
            (candidate for candidate in config.points if candidate.id == point_id),
            None,
        )
        if point is None:
            raise ValueError("unknown_modbus_point")
        value = await client.write_point(point, requested_value)
        await sync_tcp_entry(entry, client)
        return {
            "ok": True,
            "composite_id": composite.id,
            "point_id": point.id,
            "value": value,
        }
    model = find_point_model(config_id, device_id)
    point = next(
        (candidate for candidate in config.points if candidate.id == model["point_id"]),
        None,
    )
    if point is None:
        raise ValueError("unknown_modbus_point")
    if command == "refresh":
        await sync_tcp_entry(entry, client)
        return {"ok": True, "point_id": point.id}
    if command != "set_value":
        raise ValueError("unsupported_modbus_command")
    if "value" not in args:
        raise ValueError("value_required")
    value = await client.write_point(point, args["value"])
    await sync_tcp_entry(entry, client)
    return {"ok": True, "point_id": point.id, "value": value}


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(
                request.device_id or target.get("device_id") or "demo-device"
            )
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id)
            if entry is None:
                raise ValueError("Unknown configured register")
            config = DeviceConfig.model_validate(entry["config"])
            if config.points:
                executor = (
                    execute_sidecar_command
                    if config.transport in {"rtu_sidecar", "ascii_sidecar"}
                    else execute_tcp_command
                )
                result = await executor(
                    config_id=config_id,
                    device_id=device_id,
                    command=_command_name,
                    args=request.args,
                )
                return {
                    "command": _command_name,
                    "device_id": device_id,
                    "config_id": config_id,
                    "result": result,
                }
            metrics = await refresh_entry(entry)
            if not metrics.get("connected"):
                raise RuntimeError("Modbus register is unavailable")
            event = append_runtime_event(
                "runtime.command.received",
                entry,
                {
                    "command": _command_name,
                    "device_id": device_id,
                    "entity_id": request.entity_id,
                    "args": request.args,
                    "target": target,
                },
            )
            return {
                "event": event,
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "target": target,
                "params": request.args,
                "holding_register_value": metrics["holding_register_value"],
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
