from __future__ import annotations

import os
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
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .profile import decode_point, encode_point, point_metadata, profile_hash
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .transport import EventBuffer, SerialRTUSession

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
controllers: dict[str, "BusController"] = {}
session_factory: Callable[[DeviceConfig], SerialRTUSession] = SerialRTUSession


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"serial_port"}),
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
    candidate = BusController(config=config, entry=entry, session=session_factory(config))
    opened = await candidate.open()
    previous = controllers.get(config_id)
    if opened or previous is None:
        controllers[config_id] = candidate
        if previous is not None:
            await previous.close()
    else:
        await candidate.close()
        raise ValueError("serial_reconfiguration_failed_previous_session_preserved")
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        candidate.state(),
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    controller = controllers.pop(config_id, None)
    if controller is not None:
        await controller.close()
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


async def shutdown_controllers() -> None:
    active = list(controllers.values())
    controllers.clear()
    for controller in active:
        await controller.close()


class BusController:
    def __init__(
        self,
        *,
        config: DeviceConfig,
        entry: dict[str, Any],
        session: SerialRTUSession,
    ) -> None:
        self.config = config
        self.entry = entry
        self.session = session
        self.events = EventBuffer(config.event_capacity)
        self.port_open = False
        self.values: dict[str, dict[str, Any]] = {}
        self.last_error_code: str | None = None
        self.reconnect_count = 0
        self._profile_hash = profile_hash(config)

    async def open(self) -> bool:
        try:
            await self.session.open()
        except (OSError, ValueError) as exc:
            self.last_error_code = type(exc).__name__
            self.port_open = False
            return False
        self.port_open = True
        self.last_error_code = None
        self.events.append("serial.connected", {"profile_hash": self._profile_hash})
        await self.refresh_all()
        return True

    async def close(self) -> None:
        await self.session.close()
        self.port_open = False

    async def reconnect(self) -> bool:
        await self.close()
        self.reconnect_count += 1
        return await self.open()

    async def refresh_all(self) -> dict[str, dict[str, Any]]:
        for profile in self.config.registers:
            await self.refresh_point(profile.id)
        return self.values

    async def refresh_point(self, point_id: str) -> dict[str, Any]:
        profile = self.point(point_id)
        previous = self.values.get(point_id, {}).get("value")
        try:
            words = await self.session.read(profile)
            value = decode_point(profile, words)
            record = {
                "value": value,
                "quality": "good",
                "updated_at": datetime.now(UTC).isoformat(),
                "error_code": None,
            }
            self.last_error_code = None
            if previous != value:
                self.events.append(
                    "point.changed",
                    {"point_id": point_id, "previous": previous, "value": value},
                )
        except (ConnectionError, OSError, TimeoutError, ValueError) as exc:
            self.last_error_code = str(exc) or type(exc).__name__
            record = {
                **self.values.get(point_id, {}),
                "quality": "unavailable",
                "error_code": self.last_error_code,
            }
            self.events.append(
                "point.read_failed",
                {"point_id": point_id, "error_code": self.last_error_code},
            )
        self.values[point_id] = record
        self._publish_state()
        return record

    async def write_point(self, point_id: str, value: Any) -> dict[str, Any]:
        profile = self.point(point_id)
        encoded = encode_point(profile, value)
        await self.session.write(profile, encoded)
        confirmed = await self.refresh_point(point_id)
        if confirmed.get("quality") != "good" or confirmed.get("value") != value:
            raise ValueError("write_readback_mismatch")
        self.events.append("point.write_succeeded", {"point_id": point_id, "value": value})
        return confirmed

    def point(self, point_id: str):
        profile = next((item for item in self.config.registers if item.id == point_id), None)
        if profile is None:
            raise ValueError("unknown_profile_point")
        return profile

    def state(self) -> dict[str, Any]:
        responsive_units = {
            point.unit_id
            for point in self.config.registers
            if self.values.get(point.id, {}).get("quality") == "good"
        }
        return {
            "connected": self.port_open and bool(responsive_units),
            "service_available": True,
            "port_open": self.port_open,
            "responsive_unit_ids": sorted(responsive_units),
            "profile_id": self.config.profile_id,
            "profile_version": self.config.profile_version,
            "profile_hash": self._profile_hash,
            "queue_depth": self.session.queue.pending,
            "queue_capacity": self.session.queue.capacity,
            "reconnect_count": self.reconnect_count,
            "last_error_code": self.last_error_code,
            "points": self.values,
            "config_id": self.entry["config_id"],
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "piphi.modbus.snapshot.v1",
            **self.state(),
            "points": [
                {**point_metadata(point), **self.values.get(point.id, {"quality": "unknown"})}
                for point in self.config.registers
            ],
            "stream_id": self.events.stream_id,
            "latest_sequence": self.events.read().latest_sequence,
            "dropped_event_count": self.events.dropped,
        }

    def _publish_state(self) -> None:
        registry.update_state(
            str(self.entry["config_id"]),
            self.state(),
            device_id=str(self.entry["device_id"]),
        )


def get_controller(config_id: str | None = None) -> BusController:
    if config_id:
        controller = controllers.get(config_id)
    elif len(controllers) == 1:
        controller = next(iter(controllers.values()))
    else:
        controller = None
    if controller is None:
        raise HTTPException(status_code=404, detail="Unknown or ambiguous Modbus configuration")
    return controller


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "modbus-rtu-service")
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id) or {
                "device_id": device_id,
                "config_id": config_id,
            }
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
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
