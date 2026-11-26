from __future__ import annotations

import os
import hashlib
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
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .profile import decode_point, encode_point, point_metadata, profile_hash
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .transport import EventBuffer, SerialRTUSession
from .security import safe_error_code, verify_profile_trust

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
        "config": config.model_dump(exclude={"serial_port", "profile_signature"}),
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
    verify_profile_trust(
        digest=profile_hash(config),
        declared_digest=config.profile_sha256,
        signature=config.profile_signature,
    )
    configured_port = os.path.abspath(config.serial_port)
    resolved_port = os.path.realpath(config.serial_port)
    production = (
        os.getenv("PIPHI_ENV", "").lower() == "production"
        or os.getenv("ENVIRONMENT", "").lower() == "production"
    )
    if production and not configured_port.startswith("/dev/serial/by-id/"):
        raise ValueError("serial_port_outside_allowed_device_mount")
    for active_id, controller in controllers.items():
        if active_id != config_id and os.path.realpath(controller.config.serial_port) == resolved_port:
            raise ValueError("serial_port_already_configured")
    candidate = BusController(config=config, entry=entry, session=session_factory(config))
    opened = await candidate.open()
    previous = controllers.get(config_id)
    if opened or (previous is None and not production):
        controllers[config_id] = candidate
        if previous is not None:
            await previous.close()
    else:
        await candidate.close()
        if previous is not None:
            raise ValueError("serial_reconfiguration_failed_previous_session_preserved")
        raise ValueError("serial_configuration_probe_failed")
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
        self.request_success_count = 0
        self.request_failure_count = 0
        self.timeout_count = 0
        self.crc_error_count = 0
        self.lrc_error_count = 0
        self.transport_error_count = 0
        self.last_poll_duration_ms = 0.0
        self.unit_health: dict[int, dict[str, Any]] = {}
        self._profile_hash = profile_hash(config)

    async def open(self) -> bool:
        if not await self._open_port():
            return False
        await self.refresh_all()
        if self.config.registers and not any(
            value.get("quality") == "good" for value in self.values.values()
        ):
            await self.close()
            return False
        return True

    async def _open_port(self) -> bool:
        try:
            await self.session.open()
        except (OSError, ValueError) as exc:
            self.last_error_code = type(exc).__name__
            self.port_open = False
            return False
        self.port_open = True
        self.last_error_code = None
        self.events.append("serial.connected", {"profile_hash": self._profile_hash})
        return True

    async def close(self) -> None:
        await self.session.close()
        self.port_open = False

    async def reconnect(self) -> bool:
        await self.close()
        self.reconnect_count += 1
        reopened = await self._open_port()
        if reopened:
            self.events.append("serial.recovered", {"reconnect_count": self.reconnect_count})
        return reopened

    async def refresh_all(self) -> dict[str, dict[str, Any]]:
        started_at = time.monotonic()
        for profile in self.config.registers:
            await self.refresh_point(profile.id)
        self.last_poll_duration_ms = round((time.monotonic() - started_at) * 1000, 3)
        return self.values

    async def refresh_point(self, point_id: str) -> dict[str, Any]:
        started_at = time.monotonic()
        profile = self.point(point_id)
        previous = self.values.get(point_id, {}).get("value")
        health = self.unit_health.setdefault(
            profile.unit_id,
            {
                "unit_id": profile.unit_id,
                "success_count": 0,
                "failure_count": 0,
                "consecutive_error_count": 0,
                "last_success_at": None,
                "last_error_code": None,
            },
        )
        try:
            try:
                words = await self.session.read(profile)
            except (ConnectionError, OSError):
                if not await self.reconnect():
                    raise
                words = await self.session.read(profile)
            value = decode_point(profile, words)
            timestamp = datetime.now(UTC).isoformat()
            record = {
                "value": value,
                "quality": "good",
                "updated_at": timestamp,
                "error_code": None,
            }
            self.request_success_count += 1
            health.update(
                success_count=int(health["success_count"]) + 1,
                consecutive_error_count=0,
                last_success_at=timestamp,
                last_error_code=None,
            )
            self.last_error_code = None
            if previous != value:
                self.events.append(
                    "point.changed",
                    {"point_id": point_id, "previous": previous, "value": value},
                )
        except (ConnectionError, OSError, TimeoutError, ValueError) as exc:
            self.last_error_code = safe_error_code(exc)
            self.request_failure_count += 1
            if isinstance(exc, TimeoutError):
                self.timeout_count += 1
            elif self.last_error_code == "invalid_modbus_crc":
                self.crc_error_count += 1
            elif self.last_error_code == "invalid_modbus_lrc":
                self.lrc_error_count += 1
            else:
                self.transport_error_count += 1
            health.update(
                failure_count=int(health["failure_count"]) + 1,
                consecutive_error_count=int(health["consecutive_error_count"]) + 1,
                last_error_code=self.last_error_code,
            )
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
        self.last_poll_duration_ms = round((time.monotonic() - started_at) * 1000, 3)
        self._publish_state()
        return record

    async def write_point(self, point_id: str, value: Any) -> dict[str, Any]:
        if not self.config.writes_enabled:
            raise ValueError("writes_disabled")
        profile = self.point(point_id)
        encoded = encode_point(profile, value)
        try:
            await self.session.write(profile, encoded)
        except (ConnectionError, OSError) as exc:
            await self.reconnect()
            raise ConnectionError("write_outcome_unknown") from exc
        confirmed = await self.refresh_point(point_id)
        if confirmed.get("quality") != "good" or confirmed.get("value") != value:
            raise ValueError("write_readback_mismatch")
        self.events.append("point.write_succeeded", {"point_id": point_id, "value": value})
        return confirmed

    async def write_coils(
        self, point_ids: list[str], values: list[bool]
    ) -> dict[str, Any]:
        if not self.config.writes_enabled:
            raise ValueError("writes_disabled")
        points = [self.point(point_id) for point_id in point_ids]
        try:
            await self.session.write_coils(points, values)
        except (ConnectionError, OSError) as exc:
            await self.reconnect()
            raise ConnectionError("write_outcome_unknown") from exc
        confirmed = [await self.refresh_point(point_id) for point_id in point_ids]
        confirmed_values = [record.get("value") for record in confirmed]
        if confirmed_values != values or any(
            record.get("quality") != "good" for record in confirmed
        ):
            raise ValueError("write_readback_mismatch")
        self.events.append(
            "coil_group.write_succeeded",
            {"point_ids": point_ids, "values": values},
        )
        return {"point_ids": point_ids, "values": confirmed_values}

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
            "adapter_identity": hashlib.sha256(
                os.path.basename(self.config.serial_port).encode()
            ).hexdigest()[:16],
            "responsive_unit_ids": sorted(responsive_units),
            "profile_id": self.config.profile_id,
            "profile_version": self.config.profile_version,
            "profile_hash": self._profile_hash,
            "queue_depth": self.session.queue.pending,
            "queue_capacity": self.session.queue.capacity,
            "queue_high_water_mark": self.session.queue.high_water_mark,
            "reconnect_count": self.reconnect_count,
            "request_success_count": self.request_success_count,
            "request_failure_count": self.request_failure_count,
            "timeout_count": self.timeout_count,
            "crc_error_count": self.crc_error_count,
            "lrc_error_count": self.lrc_error_count,
            "transport_error_count": self.transport_error_count,
            "poll_duration_ms": self.last_poll_duration_ms,
            "unit_health": [
                dict(self.unit_health[unit_id]) for unit_id in sorted(self.unit_health)
            ],
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
