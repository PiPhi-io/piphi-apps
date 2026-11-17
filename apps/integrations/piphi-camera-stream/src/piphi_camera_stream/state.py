from __future__ import annotations

import asyncio
import logging
import os
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
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .source_probe import SourceProbeResult, probe_camera_source

logger = logging.getLogger(__name__)
_refresh_lock = asyncio.Lock()


class CameraSourceUnavailableError(RuntimeError):
    """Raised when initial camera validation cannot reach a video stream."""


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


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    source_url = config.authenticated_source_url()
    return {
        **identity,
        "alias": config.alias,
        "_source_url": source_url,
        "source_protocol": source_url.get_secret_value().split(":", 1)[0].lower(),
        "preferred_transport": config.preferred_transport,
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


def _publish_probe_state(entry: dict[str, Any], result: SourceProbeResult) -> None:
    config_id = str(entry["config_id"])
    previous_record = registry.state_snapshots.get(config_id, {})
    previous_state = previous_record.get("state", {})
    previous_available = previous_state.get("connected")
    starter.state.publish(
        config_id,
        {
            "connected": result.available,
            "available": result.available,
            "availability_reason": result.reason,
            "last_checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "alias": entry.get("alias"),
            "config_id": config_id,
            "camera_stream": {
                "available": result.available,
                "transport": "brokered",
            },
        },
        device_id=entry["device_id"],
    )
    if previous_available is True and not result.available:
        logger.warning("camera source became unavailable config_id=%s", config_id)
    elif previous_available is False and result.available:
        logger.info("camera source recovered config_id=%s", config_id)


async def refresh_entry(entry: dict[str, Any]) -> SourceProbeResult:
    async with _refresh_lock:
        result = await probe_camera_source(
            entry["_source_url"].get_secret_value(),
            preferred_transport=str(entry.get("preferred_transport") or "auto"),
        )
        config_id = str(entry["config_id"])
        if registry.get(config_id) is entry:
            _publish_probe_state(entry, result)
        return result


async def refresh_all_entries() -> list[SourceProbeResult]:
    results = []
    for entry in list(registry.entries.values()):
        results.append(await refresh_entry(entry))
    return results


async def apply_config(
    config: DeviceConfig, *, require_available: bool = False
) -> None:
    entry = make_entry(config)
    result = await probe_camera_source(
        entry["_source_url"].get_secret_value(),
        preferred_transport=entry["preferred_transport"],
    )
    if require_available and not result.available:
        raise CameraSourceUnavailableError(
            "The camera stream could not be reached with the supplied address and credentials."
        )
    registry.set(str(entry["config_id"]), entry)
    _publish_probe_state(entry, result)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"source_protocol": entry["source_protocol"], "alias": config.alias},
    )


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    registry.state_snapshots.pop(config_id, None)
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"source_protocol": entry.get("source_protocol"), "alias": entry.get("alias")},
    )
    return True


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
            if entry is None or str(entry.get("device_id")) != device_id:
                raise ValueError("camera refresh target is not configured")
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
            probe = await refresh_entry(entry)
            return {
                "event": event,
                "command": _command_name,
                "device_id": device_id,
                "config_id": config_id,
                "target": target,
                "params": request.args,
                "available": probe.available,
                "availability_reason": probe.reason,
            }

        automations.action(
            command_name,
            label=str(command_definition.get("description") or command_name),
        )(handler)


_register_automation_actions()
starter.state.provide(refresh_all_entries, source=INTEGRATION_ID)
