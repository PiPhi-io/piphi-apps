from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    AutomationRegistry,
    SQLiteAutomationIdempotencyStore,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_event_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .sidecar_client import SidecarError, ZWaveSidecarClient
from .zwave_model import entity_response, normalize_snapshot, resolve_command_value

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
node_models: dict[str, list[dict[str, Any]]] = {}
supervisors: dict[str, "SidecarSupervisor"] = {}
client_factory: Callable[[], ZWaveSidecarClient] = ZWaveSidecarClient


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "alias": config.alias,
        "config": config.model_dump(),
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    *,
    severity: str = "info",
    deliver: bool = False,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity=severity,
    )
    registry.append_event(event)
    if deliver and runtime.auth.container_id and runtime.auth.internal_token:
        schedule_event_delivery(
            process_state=runtime.process_state,
            event_client=starter.event_client,
            auth_context=runtime.auth,
            event_type=event_type,
            device=device,
            payload=payload or {},
            source=INTEGRATION_ID,
            severity=severity,
            on_error=_log_delivery_error,
        )
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def entities_for_config(config_id: str) -> list[dict[str, Any]]:
    return [entity_response(model) for model in node_models.get(config_id, [])]


def all_entities() -> list[dict[str, Any]]:
    return [
        entity_response(model)
        for config_id in sorted(node_models)
        for model in node_models[config_id]
    ]


def find_node_model(config_id: str, device_id: str) -> dict[str, Any]:
    model = next(
        (
            item
            for item in node_models.get(config_id, [])
            if str(item.get("device_id")) == device_id
        ),
        None,
    )
    if model is None:
        raise ValueError("unknown_zwave_entity")
    return model


async def apply_config(config: DeviceConfig) -> None:
    entry = make_entry(config)
    config_id = str(entry["config_id"])
    previous = supervisors.pop(config_id, None)
    if previous:
        await previous.stop()
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        {
            "connected": False,
            "alias": config.alias,
            "config_id": config_id,
            "sidecar_status": "connecting",
            "nodes": {},
        },
        device_id=entry["device_id"],
    )
    supervisor = SidecarSupervisor(entry=entry, config=config, client=client_factory())
    supervisors[config_id] = supervisor
    try:
        await supervisor.sync_snapshot(reason="config_applied")
    except (SidecarError, TypeError, ValueError) as exc:
        supervisor.record_failure(exc)
    supervisor.start()
    append_runtime_event(
        "zwave.config.applied",
        entry,
        {"alias": config.alias, "sidecar_connected": supervisor.connected},
    )


async def remove_config(config_id: str) -> bool:
    supervisor = supervisors.pop(config_id, None)
    if supervisor:
        await supervisor.stop()
    node_models.pop(config_id, None)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event("zwave.config.removed", entry, {"alias": entry.get("alias")})
    return True


async def shutdown_supervisors() -> None:
    active = list(supervisors.values())
    supervisors.clear()
    await asyncio.gather(*(supervisor.stop() for supervisor in active), return_exceptions=True)


class SidecarSupervisor:
    def __init__(
        self,
        *,
        entry: dict[str, Any],
        config: DeviceConfig,
        client: ZWaveSidecarClient,
    ) -> None:
        self.entry = entry
        self.config = config
        self.client = client
        self.config_id = str(entry["config_id"])
        self.sidecar_config_id = ""
        self.cursor = 0
        self.stream_id = ""
        self.dropped = 0
        self.connected = False
        self.last_error: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(
                self._run(), name=f"zwave-sidecar-{self.config_id}"
            )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def sync_snapshot(
        self, *, reason: str, advance_cursor: bool = True
    ) -> dict[str, Any]:
        replay_cursor = self.cursor
        replay_stream_id = self.stream_id
        snapshot = await self.client.snapshot()
        sidecar_config_id = str(snapshot.get("config_id") or "")
        if not sidecar_config_id:
            raise SidecarError("sidecar snapshot omitted config_id")
        snapshot_cursor = int(snapshot.get("latest_sequence") or 0)
        snapshot_stream_id = str(snapshot.get("stream_id") or "")
        controller = snapshot.get("controller")
        if not isinstance(controller, dict):
            raise SidecarError("sidecar snapshot omitted controller metadata")
        models = normalize_snapshot(
            snapshot,
            config_id=self.config_id,
            controller_alias=self.config.alias,
        )
        dropped = int(snapshot.get("dropped_event_count") or 0)

        self.sidecar_config_id = sidecar_config_id
        self.stream_id = snapshot_stream_id
        if advance_cursor or (replay_stream_id and snapshot_stream_id != replay_stream_id):
            self.cursor = snapshot_cursor
        else:
            self.cursor = replay_cursor
        self.dropped = dropped
        node_models[self.config_id] = models
        self.connected = bool(controller.get("lifecycle") == "ready")
        self.last_error = None
        _update_registry_from_snapshot(self, snapshot)
        if reason not in {"config_applied", "poll"}:
            append_runtime_event(
                "zwave.events.resynchronized",
                self.entry,
                {
                    "reason": reason,
                    "stream_id": self.stream_id,
                    "cursor": self.cursor,
                    "node_count": len(node_models[self.config_id]),
                },
                deliver=True,
            )
        return snapshot

    def record_failure(self, exc: Exception) -> None:
        was_connected = self.connected
        self.connected = False
        self.last_error = type(exc).__name__
        registry.update_state(
            self.config_id,
            {
                "connected": False,
                "sidecar_status": "unavailable",
                "last_error_code": self.last_error,
                "event_cursor": self.cursor,
            },
            device_id=self.entry["device_id"],
        )
        if was_connected:
            append_runtime_event(
                "zwave.sidecar.disconnected",
                self.entry,
                {"error_code": self.last_error},
                severity="warning",
                deliver=True,
            )

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                replay = await self.client.events(after=self.cursor)
                replay_stream = str(replay.get("stream_id") or "")
                replay_dropped = int(replay.get("dropped") or 0)
                if (
                    bool(replay.get("gap"))
                    or (self.stream_id and replay_stream != self.stream_id)
                    or replay_dropped < self.dropped
                ):
                    await self.sync_snapshot(reason="replay_gap_or_restart")
                else:
                    events = [event for event in replay.get("events", []) if isinstance(event, dict)]
                    if events:
                        self.cursor = int(replay.get("next_cursor") or self.cursor)
                        self.stream_id = replay_stream or self.stream_id
                        self.dropped = replay_dropped
                        for event in events:
                            self._publish_event(event)
                        await self.sync_snapshot(reason="poll", advance_cursor=False)
                if not self.connected:
                    await self.sync_snapshot(reason="sidecar_recovered")
                backoff = 1.0
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.config.event_poll_interval_seconds
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except (SidecarError, TypeError, ValueError) as exc:
                self.record_failure(exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2.0, 30.0)

    def _publish_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event_type") or "zwave.event")
        node_id = event.get("node_id")
        endpoint = event.get("endpoint", 0)
        model = next(
            (
                item
                for item in node_models.get(self.config_id, [])
                if item.get("node_id") == node_id and item.get("endpoint") == endpoint
            ),
            self.entry,
        )
        append_runtime_event(
            event_type,
            model,
            {
                "sequence": event.get("sequence"),
                "node_id": node_id,
                "endpoint": endpoint,
                "command_class": event.get("command_class"),
                "value_id": event.get("value_id"),
                "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
            },
            deliver=True,
        )


def _update_registry_from_snapshot(
    supervisor: SidecarSupervisor, snapshot: dict[str, Any]
) -> None:
    models = node_models.get(supervisor.config_id, [])
    controller = snapshot.get("controller") if isinstance(snapshot.get("controller"), dict) else {}
    registry.update_state(
        supervisor.config_id,
        {
            "connected": supervisor.connected,
            "sidecar_status": "connected",
            "alias": supervisor.config.alias,
            "config_id": supervisor.config_id,
            "event_cursor": supervisor.cursor,
            "event_stream_id": supervisor.stream_id,
            "dropped_event_count": supervisor.dropped,
            "controller": controller,
            "nodes": {model["device_id"]: model["state"] for model in models},
            "node_count": len({model["node_id"] for model in models}),
            "entity_count": len(models),
            "last_error_code": None,
        },
        device_id=supervisor.entry["device_id"],
    )


async def execute_command(
    *,
    config_id: str,
    device_id: str,
    command: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    supervisor = supervisors.get(config_id)
    if supervisor is None or not supervisor.sidecar_config_id:
        raise ValueError("sidecar_not_configured")
    if command == "reconnect_driver":
        result = await supervisor.client.command(
            config_id=supervisor.sidecar_config_id, command=command
        )
        await supervisor.sync_snapshot(reason="command_reconnect")
        return result

    model = find_node_model(config_id, device_id)
    node_id = int(model["node_id"])
    if command == "refresh":
        sidecar_command = "refresh_node_values"
        params = {"node_id": node_id}
    elif command in {"ping_node", "request_node_interview"}:
        sidecar_command = command
        params = {"node_id": node_id}
    else:
        value_id, value = resolve_command_value(
            model, command=command, value=args.get("value")
        )
        sidecar_command = "set_value"
        params = {"node_id": node_id, "value_id": value_id, "value": value}
    result = await supervisor.client.command(
        config_id=supervisor.sidecar_config_id,
        command=sidecar_command,
        params=params,
    )
    await supervisor.sync_snapshot(reason=f"command_{command}")
    append_runtime_event(
        "zwave.command.completed",
        model,
        {"command": command, "node_id": node_id},
        deliver=True,
    )
    return result


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        async def handler(request, *, _command_name=command_name):
            raw_target = getattr(request, "target", None)
            target = raw_target if isinstance(raw_target, dict) else {}
            device_id = str(getattr(request, "device_id", None) or target.get("device_id") or "")
            config_id = str(getattr(request, "config_id", None) or target.get("config_id") or "")
            if not config_id or not device_id:
                raise ValueError("config_id_and_device_id_are_required")
            result = await execute_command(
                config_id=config_id,
                device_id=device_id,
                command=_command_name,
                args=getattr(request, "args", None) or {},
            )
            return {
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "result": result,
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


def _log_delivery_error(exc: Exception, context: dict[str, Any]) -> None:
    logger.warning("zwave_event_delivery_failed error=%s context=%s", exc, context)


_register_automation_actions()
