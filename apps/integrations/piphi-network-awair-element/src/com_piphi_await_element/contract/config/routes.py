from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    ConfigSyncCoordinator,
    RuntimeConfigApplyResponse,
    RuntimeConfigRemoveResponse,
    TelemetryClient,
    build_config_apply_response,
    build_config_remove_response,
    resolve_core_base_url,
    schedule_telemetry_delivery,
)
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from com_piphi_await_element.lib.awair_client import AwairLocalClient, AwairTransportError
from com_piphi_await_element.lib.logging import log_event
from com_piphi_await_element.lib.manifest import load_manifest
from com_piphi_await_element.lib.schemas import (
    AwairElement,
    DeconfigureConfig,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
)
from com_piphi_await_element.lib.store import append_event, get_runtime_context, registry

config_router = APIRouter(tags=["config"])
CORE_BASE_URL = resolve_core_base_url("http://127.0.0.1:31419")
UNITS = {
    "pm25": "ug/m3", "pm10_est": "ug/m3", "score": "%", "co2": "ppm",
    "co2_est": "ppm", "co2_est_baseline": "ppm", "voc": "ppb",
    "voc_baseline": "ppb", "voc_h2_raw": "raw", "voc_ethanol_raw": "raw",
    "humidity": "%", "absolute_humidity": "g/m3", "temperature": "°C",
    "dew_point": "°C",
}

runtime_context = get_runtime_context()
manifest = load_manifest()
telemetry_client = TelemetryClient(
    process_state=runtime_context.process_state,
    core_base_url=CORE_BASE_URL or "http://127.0.0.1:31419",
    timeout_seconds=4.0,
)
config_sync = ConfigSyncCoordinator(process_state=runtime_context.process_state)


@dataclass
class RuntimeData:
    configs: dict[str, AwairElement] = field(default_factory=dict)
    clients: dict[str, AwairLocalClient] = field(default_factory=dict)
    tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    config_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connector: Any = AwairLocalClient.connect


runtime_data = RuntimeData()


def stable_device_id(identity: str) -> str:
    normalized = "".join(ch.lower() for ch in identity if ch.isalnum())
    if len(normalized) < 3:
        raise ValueError("device identity is invalid")
    digest = hashlib.sha256(f"awair-element:{normalized}".encode()).hexdigest()[:20]
    return f"awair-element:{digest}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _record_event(event_type: str, entry: dict[str, Any]) -> None:
    append_event(
        {
            "event_type": event_type,
            "source": manifest["id"],
            "config_id": entry.get("config_id"),
            "device_id": entry.get("device_id"),
            "severity": "info",
            "timestamp": _now(),
            "payload": {},
        }
    )


def _sync_auth(request: Request, payload: Any) -> None:
    sync_runtime_auth_from_fastapi_payload(runtime_context, request, payload)


def _schedule_state(entry: dict[str, Any], state: dict[str, Any]) -> None:
    schedule_telemetry_delivery(
        process_state=runtime_context.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime_context.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=state,
        units=UNITS,
    )


def _publish(entry: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    was_unavailable = entry.get("availability") == "unavailable"
    state = {
        **metrics,
        "available": True,
        "stale": False,
        "last_success_at": _now(),
        "consecutive_failures": 0,
    }
    entry.update(
        availability="online",
        last_success_at=state["last_success_at"],
        consecutive_failures=0,
        last_error_category=None,
    )
    config_id = str(entry["config_id"])
    registry.update_state(config_id, state, device_id=str(entry["device_id"]))
    _schedule_state(entry, state)
    if was_unavailable:
        _record_event("device.restored", entry)
    return state


def _mark_stale(entry: dict[str, Any], category: str) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    failures = int(entry.get("consecutive_failures", 0)) + 1
    previous = registry.state_snapshots.get(config_id, {}).get("state", {})
    state = {
        **previous,
        "available": False,
        "stale": True,
        "error_category": category,
        "consecutive_failures": failures,
    }
    was_online = entry.get("availability") == "online"
    entry.update(
        availability="unavailable",
        consecutive_failures=failures,
        last_error_category=category,
    )
    registry.update_state(config_id, state, device_id=str(entry["device_id"]))
    _schedule_state(entry, state)
    if was_online:
        _record_event("device.unavailable", entry)
    return state


async def _close(client: AwairLocalClient | None) -> None:
    if client is not None:
        try:
            await client.close()
        except (OSError, RuntimeError):
            log_event("awair_client_close_failed", level="debug")


async def trigger_refresh(device_or_config_id: str) -> dict[str, Any]:
    config_id = next(
        (
            key for key, value in registry.entries.items()
            if key == device_or_config_id or value.get("device_id") == device_or_config_id
        ),
        None,
    )
    if config_id is None:
        raise HTTPException(status_code=404, detail="configured device not found")
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="configured device not found")
    async with runtime_data.locks.setdefault(config_id, asyncio.Lock()):
        client = runtime_data.clients.get(config_id)
        try:
            if client is None:
                config = runtime_data.configs[config_id]
                client = await runtime_data.connector(config.device_ip)
                runtime_data.clients[config_id] = client
            metrics = await client.latest()
        except (AwairTransportError, KeyError) as exc:
            if client is not None:
                runtime_data.clients.pop(config_id, None)
                await _close(client)
            category = exc.code if isinstance(exc, AwairTransportError) else "unreachable"
            _mark_stale(entry, category)
            raise HTTPException(status_code=503, detail={"error": category}) from exc
        return {
            "device_id": entry["device_id"],
            "config_id": config_id,
            "state": _publish(entry, metrics),
        }


async def _poll(config_id: str) -> None:
    while registry.get(config_id) is not None:
        config = runtime_data.configs.get(config_id)
        if config is None:
            return
        entry = registry.get(config_id) or {}
        failures = int(entry.get("consecutive_failures", 0))
        delay = min(3600, config.poll_interval_seconds * (2 ** min(failures, 5)))
        await asyncio.sleep(delay)
        for attempt in range(3):
            try:
                await trigger_refresh(config_id)
                break
            except HTTPException:
                if attempt < 2:
                    await asyncio.sleep(min(4, 2**attempt))


async def apply_device_config(payload: AwairElement) -> dict[str, Any]:
    config_id = str(payload.config_id or payload.id)
    candidate: AwairLocalClient | None = None
    try:
        device_id = stable_device_id(payload.device_identity)
        candidate = await runtime_data.connector(payload.device_ip)
        initial = await candidate.latest()
    except ValueError as exc:
        await _close(candidate)
        raise HTTPException(status_code=422, detail={"error": "invalid_identity"}) from exc
    except AwairTransportError as exc:
        await _close(candidate)
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    except Exception as exc:
        await _close(candidate)
        log_event("awair_setup_failed", level="warning", error_type=type(exc).__name__)
        raise HTTPException(status_code=422, detail={"error": "unreachable"}) from exc

    if candidate is None:  # pragma: no cover - defensive type narrowing
        raise HTTPException(status_code=422, detail={"error": "unreachable"})

    old_client: AwairLocalClient | None = None
    old_task: asyncio.Task | None = None
    try:
        async with runtime_data.config_lock:
            duplicate = next(
                (value for key, value in registry.entries.items() if key != config_id and value.get("device_id") == device_id),
                None,
            )
            if duplicate is not None:
                raise HTTPException(status_code=409, detail={"error": "device_already_configured"})
            previous = registry.get(config_id)
            if previous is not None and previous.get("device_id") != device_id:
                raise HTTPException(status_code=409, detail={"error": "device_identity_mismatch"})
            previous_config = runtime_data.configs.get(config_id)
            previous_state = registry.state_snapshots.get(config_id)
            old_client = runtime_data.clients.get(config_id)
            old_task = runtime_data.tasks.get(config_id)
            entry = {
                "config_id": config_id,
                "container_id": payload.container_id or runtime_context.auth.container_id,
                "integration_id": payload.integration_id or manifest["id"],
                "device_id": device_id,
                "availability": "online",
                "consecutive_failures": 0,
            }
            try:
                runtime_data.configs[config_id] = payload
                runtime_data.clients[config_id] = candidate
                registry.set(config_id, entry)
                _publish(entry, initial)
                runtime_data.tasks[config_id] = asyncio.create_task(_poll(config_id))
            except Exception:
                if previous_config is None:
                    runtime_data.configs.pop(config_id, None)
                else:
                    runtime_data.configs[config_id] = previous_config
                if old_client is None:
                    runtime_data.clients.pop(config_id, None)
                else:
                    runtime_data.clients[config_id] = old_client
                if previous is None:
                    registry.entries.pop(config_id, None)
                else:
                    registry.entries[config_id] = previous
                if previous_state is None:
                    registry.state_snapshots.pop(config_id, None)
                else:
                    registry.state_snapshots[config_id] = previous_state
                raise
    except Exception:
        await _close(candidate)
        raise
    if old_task is not None:
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)
    if old_client is not candidate:
        await _close(old_client)
    _record_event("runtime.config.applied", registry.get(config_id) or {})
    log_event("config_applied")
    return build_config_apply_response(
        config_id=config_id,
        container_id=payload.container_id or runtime_context.auth.container_id,
        metadata={"device_id": device_id},
    ).model_dump()


async def restore_device_config(payload: AwairElement) -> dict[str, Any]:
    """Restore a previously accepted config even while its device is offline."""
    try:
        return await apply_device_config(payload)
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        error = exc.detail.get("error") if isinstance(exc.detail, dict) else None
        if error not in {"unreachable", "http_error", "invalid_response", "host_resolution_failed"}:
            raise
    config_id = str(payload.config_id or payload.id)
    try:
        device_id = stable_device_id(payload.device_identity)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_identity"}) from exc
    entry = {
        "config_id": config_id,
        "container_id": payload.container_id or runtime_context.auth.container_id,
        "integration_id": payload.integration_id or manifest["id"],
        "device_id": device_id,
        "availability": "unavailable",
        "consecutive_failures": 0,
    }
    async with runtime_data.config_lock:
        runtime_data.configs[config_id] = payload
        registry.set(config_id, entry)
        _mark_stale(entry, "startup_unreachable")
        runtime_data.tasks[config_id] = asyncio.create_task(_poll(config_id))
    return build_config_apply_response(
        config_id=config_id,
        container_id=str(entry["container_id"]) if entry.get("container_id") else None,
        metadata={"restored_offline": True},
    ).model_dump()


async def remove_device_config(config_id: str) -> bool:
    async with runtime_data.config_lock:
        task = runtime_data.tasks.pop(config_id, None)
        client = runtime_data.clients.pop(config_id, None)
        runtime_data.configs.pop(config_id, None)
        entry = registry.remove(config_id)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    await _close(client)
    if entry is not None:
        _record_event("runtime.config.removed", entry)
    return entry is not None


async def apply_runtime_config_snapshot(payload: RuntimeConfigSnapshot) -> RuntimeConfigSyncResponse:
    async def apply(config) -> None:
        parsed = AwairElement.model_validate(config.model_dump()).model_copy(update={
            "integration_id": config.integration_id or payload.integration_id,
            "container_id": config.container_id or payload.container_id,
        })
        await apply_device_config(parsed)

    response = await config_sync.apply_snapshot(
        snapshot=payload,
        active_config_ids=registry.ids(),
        apply_config=apply,
        remove_config=remove_device_config,
        get_active_config_ids=registry.ids,
    )
    return RuntimeConfigSyncResponse(**response.model_dump())


async def restore_runtime_config_snapshot(payload: RuntimeConfigSnapshot) -> RuntimeConfigSyncResponse:
    async def restore(config) -> None:
        parsed = AwairElement.model_validate(config.model_dump()).model_copy(update={
            "integration_id": config.integration_id or payload.integration_id,
            "container_id": config.container_id or payload.container_id,
        })
        await restore_device_config(parsed)

    response = await config_sync.apply_snapshot(
        snapshot=payload,
        active_config_ids=registry.ids(),
        apply_config=restore,
        remove_config=remove_device_config,
        get_active_config_ids=registry.ids,
    )
    return RuntimeConfigSyncResponse(**response.model_dump())


@config_router.post("/config")
async def config(payload: AwairElement, request: Request) -> RuntimeConfigApplyResponse:
    _sync_auth(request, payload)
    return RuntimeConfigApplyResponse.model_validate(await apply_device_config(payload))


@config_router.post("/configs/sync", response_model=RuntimeConfigSyncResponse)
@config_router.post("/config/sync", response_model=RuntimeConfigSyncResponse)
async def sync_configs(payload: RuntimeConfigSnapshot, request: Request):
    _sync_auth(request, payload)
    return await apply_runtime_config_snapshot(payload)


@config_router.post("/deconfigure")
async def deconfigure_device(payload: DeconfigureConfig) -> RuntimeConfigRemoveResponse:
    config_id = str(payload.config.get("config_id") or payload.config.get("id") or "").strip()
    if not config_id:
        raise HTTPException(status_code=400, detail="Missing config id")
    return build_config_remove_response(
        config_id=config_id,
        removed=await remove_device_config(config_id),
    )


@config_router.post("/refresh")
async def refresh_device(payload: DeconfigureConfig):
    config_id = str(payload.config.get("config_id") or payload.config.get("id") or "").strip()
    if not config_id:
        raise HTTPException(status_code=400, detail="Missing config id")
    return await trigger_refresh(config_id)
