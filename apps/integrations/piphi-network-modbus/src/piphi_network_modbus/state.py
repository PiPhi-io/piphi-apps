from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
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
sidecar_clients: dict[str, ModbusSidecarClient] = {}
sidecar_replay: dict[str, dict[str, Any]] = {}
sidecar_client_factory: Callable[[], ModbusSidecarClient] = ModbusSidecarClient
tcp_clients: dict[str, ModbusTCPClient] = {}
tcp_client_factory: Callable[..., ModbusTCPClient] = ModbusTCPClient


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
    if config.transport == "rtu_sidecar":
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
                    "transport": "rtu_sidecar",
                    "quality": "unavailable",
                    "last_error_code": type(exc).__name__,
                    "config_id": config_id,
                },
                device_id=entry["device_id"],
            )
        append_runtime_event(
            "runtime.config.applied",
            entry,
            {"transport": "rtu_sidecar", "alias": config.alias},
        )
        return
    if config.points:
        client = tcp_client_factory(
            config.host, timeout=config.response_timeout_seconds
        )
        tcp_clients[config_id] = client
        await sync_tcp_entry(entry, client)
        append_runtime_event(
            "runtime.config.applied",
            entry,
            {"transport": "tcp", "profile_id": config.profile_id, "alias": config.alias},
        )
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


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config = DeviceConfig.model_validate(entry["config"])
    if config.transport == "rtu_sidecar":
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
                "transport": "rtu_sidecar",
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
                config.host, timeout=config.response_timeout_seconds
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
    entry["next_poll_at"] = time.monotonic() + max(
        60, config.poll_interval_seconds or 300
    )
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
        await asyncio.sleep(5)
        now = time.monotonic()
        for entry in list(registry.entries.values()):
            if entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 300
            await refresh_entry(entry)


async def remove_config(config_id: str) -> bool:
    point_models.pop(config_id, None)
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


async def sync_tcp_entry(
    entry: dict[str, Any], client: ModbusTCPClient
) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    config = DeviceConfig.model_validate(entry["config"])
    snapshot = await client.snapshot(config.points)
    snapshot.update(
        profile_id=config.profile_id,
        profile_version=config.profile_version,
        profile_hash=profile_hash(
            profile_id=config.profile_id,
            profile_version=config.profile_version,
            profile_provenance=config.profile_provenance,
            points=config.points,
        ),
    )
    models = normalize_snapshot(snapshot, config_id=config_id)
    point_models[config_id] = models
    state = {
        "connected": bool(snapshot.get("connected")),
        "transport": "tcp",
        "quality": "good" if snapshot.get("connected") else "unavailable",
        "profile_id": snapshot["profile_id"],
        "profile_version": snapshot["profile_version"],
        "profile_hash": snapshot["profile_hash"],
        "responsive_unit_ids": snapshot.get("responsive_unit_ids", []),
        "request_count": snapshot.get("request_count", 0),
        "points": {model["point_id"]: model["state"] for model in models},
        "config_id": config_id,
        "last_error_code": snapshot.get("last_error_code"),
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    entry["next_poll_at"] = time.monotonic() + max(
        5, config.poll_interval_seconds or 15
    )
    return state


async def sync_sidecar_entry(
    entry: dict[str, Any], client: ModbusSidecarClient
) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    snapshot = await client.snapshot(config_id)
    models = normalize_snapshot(snapshot, config_id=config_id)
    point_models[config_id] = models
    state = {
        "connected": bool(snapshot.get("connected")),
        "transport": "rtu_sidecar",
        "quality": "good" if snapshot.get("connected") else "unavailable",
        "profile_id": snapshot.get("profile_id"),
        "profile_version": snapshot.get("profile_version"),
        "profile_hash": snapshot.get("profile_hash"),
        "port_open": snapshot.get("port_open"),
        "responsive_unit_ids": snapshot.get("responsive_unit_ids", []),
        "queue_depth": snapshot.get("queue_depth"),
        "queue_capacity": snapshot.get("queue_capacity"),
        "points": {model["point_id"]: model["state"] for model in models},
        "config_id": config_id,
        "last_error_code": snapshot.get("last_error_code"),
    }
    registry.update_state(config_id, state, device_id=entry["device_id"])
    config = DeviceConfig.model_validate(entry["config"])
    entry["next_poll_at"] = time.monotonic() + max(
        5, config.poll_interval_seconds or 15
    )
    return state


def sidecar_config_payload(config: DeviceConfig) -> dict[str, Any]:
    payload = config.model_dump(exclude={"api_key", "base_url"})
    payload["registers"] = payload.pop("points")
    payload["host"] = "modbus-rtu-sidecar"
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
        for config_id in sorted(point_models)
        for model in point_models[config_id]
    ]


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


async def execute_sidecar_command(
    *, config_id: str, device_id: str, command: str, args: dict[str, Any]
) -> dict[str, Any]:
    client = sidecar_clients.get(config_id)
    entry = registry.get(config_id)
    if client is None or entry is None:
        raise ValueError("sidecar_not_configured")
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
                    if config.transport == "rtu_sidecar"
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
