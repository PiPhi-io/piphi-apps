from __future__ import annotations

import asyncio
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
)

from .contract import CAPABILITIES, COMMANDS
from .parent_contract_v1 import KeyEvent, PropertyQuery, Request
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .transport import (
    AdbCommandTimeoutError,
    AdbIdentityMismatchError,
    AdbOfflineError,
    AdbOutcomeUnknownError,
    AdbSession,
    AdbTransportError,
    AdbUnauthorizedError,
)

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
controllers: dict[str, AdbController] = {}
session_factory: Callable[[DeviceConfig], AdbSession] = AdbSession


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "alias": config.alias,
        "config": config.model_dump(exclude={"host"}),
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
    if controllers and config_id not in controllers:
        raise ValueError("adb_sidecar_supports_one_target")
    for active_id, controller in controllers.items():
        if active_id != config_id and (
            controller.config.host,
            controller.config.port,
        ) == (config.host, config.port):
            raise ValueError("adb_endpoint_already_configured")
    candidate = AdbController(
        config=config,
        entry=entry,
        session=session_factory(config),
    )
    opened = await candidate.open()
    previous = controllers.get(config_id)
    if not opened:
        await candidate.close()
        if previous is not None:
            raise ValueError("adb_reconfiguration_failed_previous_session_preserved")
        raise ValueError("adb_target_not_ready")
    controllers[config_id] = candidate
    if previous is not None:
        if previous.session.endpoint == candidate.session.endpoint:
            await previous.retire()
        else:
            await previous.close()
    registry.set(config_id, entry)
    registry.update_state(
        config_id,
        candidate.state(),
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"alias": config.alias},
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
        {"alias": entry.get("alias")},
    )
    return True


async def shutdown_controllers() -> None:
    active = list(controllers.values())
    controllers.clear()
    for controller in active:
        await controller.close()


class AdbController:
    def __init__(
        self,
        *,
        config: DeviceConfig,
        entry: dict[str, Any],
        session: AdbSession,
    ) -> None:
        self.config = config
        self.entry = entry
        self.session = session
        self.lifecycle = "starting"
        self.last_error_code: str | None = None
        self.reconnect_count = 0
        self.request_success_count = 0
        self.request_failure_count = 0
        self.timeout_count = 0
        self.transport_error_count = 0
        self.last_operation_duration_ms = 0.0
        self._closed = False
        self._recovery_task: asyncio.Task[None] | None = None

    async def open(self) -> bool:
        self.lifecycle = "connecting"
        try:
            await self.session.open()
        except AdbUnauthorizedError:
            self.lifecycle = "unauthorized"
            self.last_error_code = "unauthorized"
            self._publish_state()
            return False
        except AdbIdentityMismatchError:
            self.lifecycle = "degraded"
            self.last_error_code = "identity_mismatch"
            self._publish_state()
            return False
        except (AdbTransportError, OSError):
            self.lifecycle = "offline"
            self.last_error_code = "offline"
            self._publish_state()
            return False
        self.lifecycle = "ready"
        self.last_error_code = None
        self._publish_state()
        return True

    async def close(self) -> None:
        self._closed = True
        task, self._recovery_task = self._recovery_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.session.queue.run_exclusive(self.session.close)
        self.lifecycle = "stopped"

    async def retire(self) -> None:
        """Stop an replaced controller without disconnecting its live endpoint."""
        self._closed = True
        task, self._recovery_task = self._recovery_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.session.connected = False
        self.session.authorized = False
        self.lifecycle = "stopped"

    async def reconnect(self) -> bool:
        async def operation() -> bool:
            self.reconnect_count += 1
            await self.session.close()
            return await self.open()

        return await self.session.queue.submit(operation)

    async def execute(self, request: Request) -> dict[str, Any]:
        if not self.session.target_id or request.target.target_id != self.session.target_id:
            raise ValueError("unknown_target_lease")
        started_at = time.monotonic()
        try:
            if self.lifecycle != "ready" and not await self.reconnect():
                if self.lifecycle == "unauthorized":
                    raise AdbUnauthorizedError("adb_target_unauthorized")
                raise AdbOfflineError("adb_target_offline")
            if isinstance(request.command, PropertyQuery):
                try:
                    values = await self.session.query_properties(
                        request.command.properties,
                        timeout_ms=request.timeout_ms,
                    )
                except AdbOfflineError:
                    if not await self.reconnect():
                        raise
                    values = await self.session.query_properties(
                        request.command.properties,
                        timeout_ms=request.timeout_ms,
                    )
                result: dict[str, Any] = {
                    "operation": "property_query",
                    "properties": values,
                }
            elif isinstance(request.command, KeyEvent):
                try:
                    completed = await self.session.send_key(
                        request.command.key,
                        request.command.repeat,
                        timeout_ms=request.timeout_ms,
                    )
                except AdbOutcomeUnknownError:
                    self._schedule_recovery()
                    raise
                result = {
                    "operation": "key_event",
                    "repeats_completed": completed,
                }
            else:  # pragma: no cover - discriminated contract is closed
                raise TypeError("unsupported_operation")
            self.request_success_count += 1
            self.last_error_code = None
            return result
        except AdbCommandTimeoutError:
            self.timeout_count += 1
            self.request_failure_count += 1
            self.last_error_code = "timeout"
            raise
        except (AdbTransportError, OSError):
            self.transport_error_count += 1
            self.request_failure_count += 1
            if self.last_error_code is None:
                self.last_error_code = "transport_error"
            raise
        finally:
            self.last_operation_duration_ms = round(
                (time.monotonic() - started_at) * 1000,
                3,
            )
            self._publish_state()

    def state(self) -> dict[str, Any]:
        metadata = self.session.metadata
        return {
            "connected": bool(self.session.connected and self.lifecycle == "ready"),
            "authorized": bool(self.session.authorized),
            "lifecycle": self.lifecycle,
            "service_available": True,
            "target_id": self.session.target_id,
            "device_manufacturer": metadata.get("ro.product.manufacturer"),
            "device_model": metadata.get("ro.product.model"),
            "android_release": metadata.get("ro.build.version.release"),
            "android_sdk": metadata.get("ro.build.version.sdk"),
            "queue_depth": self.session.queue.pending,
            "queue_capacity": self.session.queue.capacity,
            "queue_high_water_mark": self.session.queue.high_water_mark,
            "reconnect_count": self.reconnect_count,
            "request_success_count": self.request_success_count,
            "request_failure_count": self.request_failure_count,
            "timeout_count": self.timeout_count,
            "transport_error_count": self.transport_error_count,
            "operation_duration_ms": self.last_operation_duration_ms,
            "last_error_code": self.last_error_code,
            "config_id": self.entry["config_id"],
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": "piphi.adb.snapshot.v1",
            **self.state(),
        }

    def record_request_timeout(self) -> None:
        self.timeout_count += 1
        self.request_failure_count += 1
        self.last_error_code = "timeout"
        self._publish_state()

    def _schedule_recovery(self) -> None:
        if self._closed or (
            self._recovery_task is not None and not self._recovery_task.done()
        ):
            return
        self._recovery_task = asyncio.create_task(self._recover_bounded())

    async def _recover_bounded(self) -> None:
        for delay in (0.25, 0.5, 1.0):
            if self._closed:
                return
            await asyncio.sleep(delay)
            if await self.reconnect():
                return

    def _publish_state(self) -> None:
        if registry.get(str(self.entry["config_id"])) is not None:
            registry.update_state(
                str(self.entry["config_id"]),
                self.state(),
                device_id=str(self.entry["device_id"]),
            )


def get_controller(config_id: str | None = None) -> AdbController:
    if config_id:
        controller = controllers.get(config_id)
    elif len(controllers) == 1:
        controller = next(iter(controllers.values()))
    else:
        controller = None
    if controller is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown or ambiguous Android ADB configuration",
        )
    return controller


def get_controller_by_target(target_id: str) -> AdbController | None:
    return next(
        (
            controller
            for controller in controllers.values()
            if controller.session.target_id == target_id
        ),
        None,
    )


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():
        def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(request.device_id or target.get("device_id") or "android-adb-service")
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
