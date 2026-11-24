from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    schedule_telemetry_delivery,
)

from .contract import CAPABILITIES, COMMANDS
from .kaiterra import (
    DEFAULT_BASE_URL,
    KaiterraAuthError,
    KaiterraClient,
    KaiterraDeviceMetadata,
    KaiterraError,
    KaiterraRateLimitError,
    KaiterraReading,
    KaiterraSelectionError,
)
from .schemas import DeviceConfig
from .security import redact
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

logger = logging.getLogger(__name__)
MASKED_SECRETS = {"********", "••••••••", "***"}
MAX_BACKOFF_SECONDS = 3600

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
capabilities = CAPABILITIES
commands = COMMANDS


@dataclass(slots=True)
class RuntimeData:
    configs: dict[str, DeviceConfig] = field(default_factory=dict)
    clients: dict[str, KaiterraClient] = field(default_factory=dict)
    poll_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    client_factory: Callable[..., KaiterraClient] = KaiterraClient
    jitter: Callable[[float, float], float] = random.uniform


runtime_data = RuntimeData()
# Compatibility aliases used by existing diagnostics and downstream tests.
_clients = runtime_data.clients
_poll_tasks = runtime_data.poll_tasks


def _config_id(config: DeviceConfig) -> str:
    return str(config.config_id or config.id)


def _udid(config: DeviceConfig) -> str:
    return config.device_udid.get_secret_value()


def _api_key(config: DeviceConfig) -> str:
    return config.api_key.get_secret_value()


def device_ref(device_udid: str) -> str:
    return hashlib.sha256(f"kaiterra-device-v1\0{device_udid.lower()}".encode()).hexdigest()[:32]


def _resolved_config(config: DeviceConfig) -> DeviceConfig:
    api_key = _api_key(config)
    if api_key not in MASKED_SECRETS:
        return config
    previous = runtime_data.configs.get(_config_id(config))
    if previous is None or device_ref(_udid(previous)) != device_ref(_udid(config)):
        raise HTTPException(status_code=422, detail={"error": "api_key_required"})
    return config.model_copy(update={"api_key": previous.api_key})


def make_entry(config: DeviceConfig, metadata: KaiterraDeviceMetadata) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    ref = device_ref(_udid(config))
    return {
        **identity,
        "device_id": f"{INTEGRATION_ID}:{ref}",
        "device_ref": ref,
        "alias": config.alias or metadata.name or "Kaiterra air monitor",
        "model": metadata.model,
        "firmware_version": metadata.firmware_version,
        "base_url": config.base_url or DEFAULT_BASE_URL,
        "poll_interval_seconds": config.poll_interval_seconds,
        "consecutive_failures": 0,
        "availability": "online",
        "retry_after_seconds": None,
    }


def append_runtime_event(
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    *,
    severity: str = "info",
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=device,
        payload=redact(payload or {}),
        source=INTEGRATION_ID,
        severity=severity,
    )
    registry.append_event(event)
    return event


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"error": "unknown_configuration"})
    return entry


async def apply_config(config: DeviceConfig) -> None:
    """Validate a complete candidate before atomically replacing live state."""
    config = _resolved_config(config)
    config_id = _config_id(config)
    ref = device_ref(_udid(config))
    duplicate = next(
        (
            item_id for item_id, item in registry.entries.items()
            if item_id != config_id and item.get("device_ref") == ref
        ),
        None,
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail={"error": "device_already_configured"})
    current = registry.get(config_id)
    if current is not None and current.get("device_ref") != ref:
        raise HTTPException(
            status_code=409,
            detail={"error": "immutable_device_identity", "message": "Create a new configuration for another device."},
        )

    candidate = runtime_data.client_factory(
        api_key=_api_key(config),
        base_url=config.base_url,
    )
    try:
        reading, metadata = await _read_provider(candidate, config)
        entry = make_entry(config, metadata)
        initial_state = _success_state(entry, reading)
    except Exception as exc:
        await _close_client_safely(candidate)
        raise _setup_error(exc) from None

    async with runtime_data.lock:
        old_task = runtime_data.poll_tasks.pop(config_id, None)
        old_client = runtime_data.clients.get(config_id)
        registry.set(config_id, entry)
        runtime_data.configs[config_id] = config
        runtime_data.clients[config_id] = candidate
        _publish_success(entry, reading, state=initial_state)
        runtime_data.poll_tasks[config_id] = asyncio.create_task(
            _poll_entry(config_id), name=f"kaiterra-poll-{config_id}"
        )
    if old_task:
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)
    if old_client and old_client is not candidate:
        await _close_client_safely(old_client)
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"device_ref": ref, "model": metadata.model},
    )


async def remove_config(config_id: str) -> bool:
    async with runtime_data.lock:
        task = runtime_data.poll_tasks.pop(config_id, None)
        client = runtime_data.clients.pop(config_id, None)
        runtime_data.configs.pop(config_id, None)
        entry = registry.remove(config_id)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    if client:
        await _close_client_safely(client)
    if entry is None:
        return False
    append_runtime_event("runtime.config.removed", entry, {"device_ref": entry.get("device_ref")})
    return True


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    config_id = str(entry["config_id"])
    client = runtime_data.clients.get(config_id)
    config = runtime_data.configs.get(config_id)
    if client is None or config is None:
        return _record_failure(entry, KaiterraAuthError("credentials_unavailable"))
    try:
        reading, metadata = await _read_provider(client, config)
    except Exception as exc:
        return _record_failure(entry, exc)
    entry["alias"] = config.alias or metadata.name or entry["alias"]
    entry["model"] = metadata.model
    entry["firmware_version"] = metadata.firmware_version
    return _publish_success(entry, reading)


async def _read_provider(
    client: KaiterraClient, config: DeviceConfig
) -> tuple[KaiterraReading, KaiterraDeviceMetadata]:
    selected_udid = _udid(config)
    reading = await client.latest_reading(selected_udid)
    metadata = await client.device_metadata(selected_udid)
    return reading, metadata


def _success_state(entry: dict[str, Any], reading: KaiterraReading) -> dict[str, Any]:
    fetched_at = datetime.now(UTC)
    age = max(0.0, (fetched_at - reading.observed_at).total_seconds())
    stale = age > max(900, int(entry["poll_interval_seconds"]) * 3)
    return {
        **reading.metrics,
        "connected": True,
        "available": not stale,
        "stale": stale,
        "device_ref": entry["device_ref"],
        "name": entry["alias"],
        "model": entry.get("model"),
        "latest_timestamp": reading.latest_timestamp,
        "source_observed_at": reading.observed_at.isoformat(),
        "fetched_at": fetched_at.isoformat(),
        "source_age_seconds": int(age),
        "last_success_at": fetched_at.isoformat(),
        "error_class": None,
        "reauth_required": False,
        "retry_after_seconds": None,
    }


def _publish_success(
    entry: dict[str, Any],
    reading: KaiterraReading,
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = state or _success_state(entry, reading)
    recovered = int(entry.get("consecutive_failures", 0)) > 0
    previous_fingerprint = entry.get("reading_fingerprint")
    fingerprint = (
        reading.latest_timestamp,
        tuple(sorted(reading.metrics.items())),
    )
    registry.update_state(str(entry["config_id"]), state, device_id=str(entry["device_id"]))
    entry["latest_metrics"] = dict(reading.metrics)
    entry["latest_units"] = dict(reading.units)
    entry["last_success_at"] = state["last_success_at"]
    entry["consecutive_failures"] = 0
    entry["availability"] = "online"
    entry["retry_after_seconds"] = None
    entry["reading_fingerprint"] = fingerprint
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=reading.metrics,
        units=reading.units,
        timestamp=reading.observed_at.isoformat(),
    )
    append_runtime_event(
        "kaiterra.readings.refreshed",
        entry,
        {"device_ref": entry["device_ref"], "metric_count": len(reading.metrics)},
    )
    if previous_fingerprint is not None and previous_fingerprint != fingerprint:
        append_runtime_event(
            "device.state_changed",
            entry,
            {
                "device_ref": entry["device_ref"],
                "changed_metrics": sorted(reading.metrics),
                "source_observed_at": reading.observed_at.isoformat(),
            },
        )
    if recovered:
        append_runtime_event("kaiterra.recovered", entry, {"device_ref": entry["device_ref"]})
    return state


def _record_failure(entry: dict[str, Any], exc: Exception) -> dict[str, Any]:
    category = _error_class(exc)
    first_failure = int(entry.get("consecutive_failures", 0)) == 0
    previous = dict(registry.state_snapshots.get(str(entry["config_id"]), {}).get("state", {}))
    retry_after = exc.retry_after_seconds if isinstance(exc, KaiterraError) else None
    state = {
        **previous,
        "connected": False,
        "available": False,
        "stale": True,
        "device_ref": entry["device_ref"],
        "error_class": category,
        "reauth_required": isinstance(exc, KaiterraAuthError),
        "retry_after_seconds": retry_after,
        "last_success_at": entry.get("last_success_at"),
        "last_poll_failed_at": datetime.now(UTC).isoformat(),
    }
    registry.update_state(str(entry["config_id"]), state, device_id=str(entry["device_id"]))
    entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
    entry["availability"] = "reauth_required" if isinstance(exc, KaiterraAuthError) else category
    entry["retry_after_seconds"] = retry_after
    if first_failure:
        append_runtime_event(
            "kaiterra.unavailable",
            entry,
            {"error_class": category},
            severity="warning",
        )
    return state


def _error_class(exc: Exception) -> str:
    if isinstance(exc, KaiterraAuthError):
        return "authentication" if exc.category != "authorization" else "authorization"
    if isinstance(exc, KaiterraRateLimitError):
        return "rate_limit"
    if isinstance(exc, KaiterraSelectionError):
        return exc.category
    if isinstance(exc, KaiterraError):
        return exc.category
    return "transient_outage"


def _setup_error(exc: Exception) -> HTTPException:
    category = _error_class(exc)
    if category in {"authentication", "authorization"}:
        return HTTPException(status_code=401, detail={"error": category, "message": "Kaiterra rejected the API key or selected device access."})
    if category == "rate_limit":
        return HTTPException(status_code=429, detail={"error": category, "retry_after_seconds": getattr(exc, "retry_after_seconds", None)})
    if category in {"device_not_found", "request_rejected", "provider_contract"}:
        return HTTPException(status_code=422, detail={"error": category})
    return HTTPException(status_code=503, detail={"error": "transient_outage"})


async def refresh_all_entries() -> list[dict[str, Any]]:
    return [await refresh_entry(entry) for entry in list(registry.entries.values())]


starter.state.provide(refresh_all_entries, source=INTEGRATION_ID)


def _poll_delay(entry: dict[str, Any]) -> float:
    retry_after = entry.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)):
        base = min(
            max(float(retry_after), float(entry["poll_interval_seconds"])),
            MAX_BACKOFF_SECONDS,
        )
    else:
        failures = min(int(entry.get("consecutive_failures", 0)), 5)
        base = min(int(entry["poll_interval_seconds"]) * (2 ** failures), MAX_BACKOFF_SECONDS)
    jitter = runtime_data.jitter(0.0, min(base * 0.1, 30.0))
    return min(base + max(jitter, 0.0), MAX_BACKOFF_SECONDS)


async def _poll_entry(config_id: str) -> None:
    while True:
        entry = registry.get(config_id)
        if entry is None:
            return
        try:
            await asyncio.sleep(_poll_delay(entry))
            current = registry.get(config_id)
            if current is None:
                return
            await refresh_entry(current)
        except asyncio.CancelledError:
            raise


async def _close_client_safely(client: KaiterraClient) -> None:
    try:
        await client.close()
    except Exception as exc:  # cleanup must not replace the primary outcome
        logger.debug("kaiterra_client_close_failed error=%s", type(exc).__name__)


async def shutdown() -> None:
    for config_id in list(set(runtime_data.poll_tasks) | set(runtime_data.clients)):
        await remove_config(config_id)
