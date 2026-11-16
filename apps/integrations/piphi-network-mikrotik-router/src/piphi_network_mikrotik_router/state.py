from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import httpx
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
from .routeros import RouterOSError, RouterResources, fetch_resources
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

logger = logging.getLogger(__name__)
router_passwords: dict[str, str] = {}

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
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
        "config": config.model_dump(exclude={"api_key", "password"}),
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
    password = config.secret_password()
    resources = await fetch_resources(
        config.host,
        str(config.username),
        password,
        ca_bundle_path=config.ca_bundle_path,
    )
    entry["device_id"] = _opaque_device_id(resources.appliance_identifier)
    existing = registry.get(str(entry["config_id"]))
    if existing is not None and existing.get("device_id") != entry["device_id"]:
        raise ValueError("Reconfiguration resolved to a different RouterOS appliance")
    duplicate = next(
        (
            item
            for item in registry.entries.values()
            if item.get("device_id") == entry["device_id"]
            and item.get("config_id") != entry["config_id"]
        ),
        None,
    )
    if duplicate is not None:
        raise ValueError("This RouterOS appliance is already configured")
    router_passwords[entry["config_id"]] = password
    registry.set(entry["config_id"], entry)
    registry.update_state(
        entry["config_id"],
        {
            "connected": False,
            "host": config.host,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    await _apply_resources(entry, resources)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {},
    )


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    password = router_passwords.get(str(entry["config_id"]))
    if not password:
        state = {"connected": False, "reason": "missing_router_credentials"}
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state
    config = DeviceConfig.model_validate({**entry["config"], "password": password})
    try:
        resources = await fetch_resources(
            config.host,
            config.username,
            password,
            ca_bundle_path=config.ca_bundle_path,
        )
        return await _apply_resources(entry, resources)
    except RouterOSError as exc:
        logger.warning(
            "router_resource_refresh_failed router_ref=%s error=%s",
            _private_router_ref(entry),
            type(exc).__name__,
        )
        state = {
            "connected": False,
            "reason": exc.reason,
            "last_attempt_at": _now(),
            "last_success_at": entry.get("last_success_at"),
            "stale": bool(entry.get("last_success_at")),
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        _schedule_failure(entry, retryable=exc.retryable)
        return state
    except (httpx.HTTPError, OSError, TypeError, ValueError) as exc:
        logger.warning(
            "router_resource_refresh_failed router_ref=%s error=%s",
            _private_router_ref(entry),
            type(exc).__name__,
        )
        state = {"connected": False, "reason": "router_resource_fetch_failed", "last_attempt_at": _now(), "last_success_at": entry.get("last_success_at"), "stale": bool(entry.get("last_success_at"))}
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        _schedule_failure(entry, retryable=False)
        return state
async def _apply_resources(entry: dict[str, Any], resources: RouterResources) -> dict[str, Any]:
    observed_device_id = _opaque_device_id(resources.appliance_identifier)
    if (
        str(entry.get("device_id", "")).startswith("mikrotik-")
        and observed_device_id != entry["device_id"]
    ):
        raise RouterOSError("appliance_identity_changed", retryable=False)
    observed_at = _now()
    metrics = {
        "connected": True,
        "cpu_load_percent": resources.cpu_load_percent,
        "memory_used_percent": resources.memory_used_percent,
        "routeros_version": resources.routeros_version,
        "last_attempt_at": observed_at,
        "last_success_at": observed_at,
        "stale": False,
    }
    registry.update_state(entry["config_id"], metrics, device_id=entry["device_id"])
    entry["latest_metrics"] = metrics
    entry["last_success_at"] = observed_at
    entry["failure_count"] = 0
    entry["next_poll_at"] = time.monotonic() + max(
        60, int(entry.get("config", {}).get("poll_interval_seconds") or 300)
    )
    task = schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={"cpu_load_percent": "%", "memory_used_percent": "%"},
    )
    if task is not None:
        task.add_done_callback(
            lambda completed: (
                completed.exception() if not completed.cancelled() else None
            )
        )
    return metrics


def _schedule_failure(entry: dict[str, Any], *, retryable: bool) -> None:
    failures = int(entry.get("failure_count", 0)) + 1
    entry["failure_count"] = failures
    base = min(900, 60 * (2 ** min(failures - 1, 4))) if retryable else 900
    digest = int(sha256(str(entry["config_id"]).encode()).hexdigest()[:4], 16)
    jitter = (digest % 21 - 10) / 100
    entry["next_poll_at"] = time.monotonic() + base * (1 + jitter)


def _opaque_device_id(appliance_identifier: str) -> str:
    digest = sha256(f"{INTEGRATION_ID}\0{appliance_identifier}".encode()).hexdigest()[:24]
    return f"mikrotik-{digest}"


def _private_router_ref(entry: dict[str, Any]) -> str:
    return sha256(
        f"{INTEGRATION_ID}\0log\0{entry.get('config_id', '')}".encode()
    ).hexdigest()[:12]


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def poll_routers() -> None:
    while True:
        await asyncio.sleep(5)
        now = time.monotonic()
        for entry in list(registry.entries.values()):
            if entry.get("next_poll_at", 0) > now:
                continue
            entry["next_poll_at"] = now + 300
            await refresh_entry(entry)


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    router_passwords.pop(config_id, None)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {},
    )
    return True


def _register_automation_actions() -> None:
    for command_name, command_definition in commands.items():

        async def handler(request, *, _command_name=command_name):
            target = getattr(request, "target", None)
            target = target if isinstance(target, dict) else {}
            device_id = str(
                request.device_id or target.get("device_id") or "configured-router"
            )
            config_id = str(request.config_id or target.get("config_id") or device_id)
            entry = registry.get(config_id)
            if entry is None:
                raise ValueError("Unknown configured router")
            metrics = await refresh_entry(entry)
            if not metrics.get("connected"):
                raise RuntimeError("Router resources are unavailable")
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
                "cpu_load_percent": metrics["cpu_load_percent"],
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
