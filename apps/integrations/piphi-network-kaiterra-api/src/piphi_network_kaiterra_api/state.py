from __future__ import annotations

import asyncio
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
    KaiterraClient,
    KaiterraError,
    is_placeholder_api_key,
    resolve_device_udid,
)
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION

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
_clients: dict[str, KaiterraClient] = {}
_poll_tasks: dict[str, asyncio.Task[None]] = {}


def _secret(config: DeviceConfig) -> str | None:
    return config.api_key.get_secret_value() if config.api_key else None


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    device_udid = resolve_device_udid(config)
    return {
        **identity,
        "host": device_udid,
        "device_udid": device_udid,
        "alias": config.alias or device_udid,
        "base_url": config.base_url or DEFAULT_BASE_URL,
        "config": config.model_dump(exclude={"api_key"}),
        "poll_interval_seconds": config.poll_interval_seconds,
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
    current = registry.get(config.id)
    if current and current.get("device_udid") != entry["device_udid"]:
        raise HTTPException(status_code=409, detail="device_udid is immutable; create a new configuration")
    if any(
        other.get("device_udid") == entry["device_udid"] and other.get("config_id") != config.id
        for other in registry.entries.values()
    ):
        raise HTTPException(status_code=409, detail="device_udid is already configured")
    state = {
        "connected": False,
        "host": entry["device_udid"],
        "device_udid": entry["device_udid"],
        "alias": entry["alias"],
        "base_url": entry["base_url"],
        "config_id": entry["config_id"],
    }
    api_key = _secret(config)
    if not is_placeholder_api_key(api_key):
        candidate = KaiterraClient(api_key=api_key or "", base_url=config.base_url)
        try:
            reading, metadata = await _read_provider(candidate, entry)
        except Exception as exc:
            await _close_client_safely(candidate)
            raise _setup_error(exc) from None
        await _activate_config(config.id, entry, candidate)
        state.update(_publish_success(entry, reading, metadata))
    else:
        if current and config.id in _clients:
            raise HTTPException(status_code=400, detail="credentials are required to replace an active configuration")
        await _activate_config(config.id, entry, None)
        registry.update_state(config.id, state, device_id=entry["device_id"])
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {
            "device_udid": entry["device_udid"],
            "alias": entry["alias"],
            "base_url": entry["base_url"],
            "live_api_skipped": is_placeholder_api_key(api_key),
        },
    )


async def remove_config(config_id: str) -> bool:
    await _stop_config(config_id)
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event(
        "runtime.config.removed",
        entry,
        {"host": entry.get("host"), "alias": entry.get("alias")},
    )
    return True


async def refresh_entry(entry: dict[str, Any]) -> dict[str, Any]:
    client = _clients.get(entry["config_id"])
    if client is None:
        state = {
            "connected": False,
            "device_udid": entry["device_udid"],
            "reason": "missing_api_key",
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state

    fetched_at = datetime.now(UTC)
    try:
        reading, metadata = await _read_provider(client, entry)
    except Exception as exc:
        category = exc.category if isinstance(exc, KaiterraError) else "outage"
        first_failure = int(entry.get("consecutive_failures", 0)) == 0
        previous = dict(entry.get("latest_state") or {})
        state = {
            **previous,
            "connected": False,
            "available": False,
            "stale": True,
            "device_udid": entry["device_udid"],
            "error_class": category,
            "last_success_at": entry.get("last_success_at"),
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        if first_failure:
            append_runtime_event("kaiterra.unavailable", entry, {"error_class": category})
        return state
    return _publish_success(entry, reading, metadata, fetched_at=fetched_at)


async def _read_provider(client: KaiterraClient, entry: dict[str, Any]):
    reading = await client.latest_reading(entry["device_udid"])
    metadata = await client.device_metadata(entry["device_udid"])
    returned_udid = next(
        (str(metadata[key]) for key in ("udid", "device_udid", "id") if metadata.get(key)),
        None,
    )
    if returned_udid is not None and returned_udid != entry["device_udid"]:
        raise KaiterraError("identity_mismatch")
    return reading, metadata


def _publish_success(
    entry: dict[str, Any],
    reading,
    metadata: dict[str, Any],
    *,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(UTC)
    age = max(0.0, (fetched_at - reading.observed_at).total_seconds())
    stale = age > max(900, int(entry["poll_interval_seconds"]) * 3)
    state = {
        **reading.metrics,
        "connected": True,
        "available": not stale,
        "stale": stale,
        "device_udid": entry["device_udid"],
        "latest_timestamp": reading.latest_timestamp,
        "name": metadata.get("name") or metadata.get("label") or entry.get("alias"),
        "api_latency_ms": reading.latency_ms,
        "source_observed_at": reading.observed_at.isoformat(),
        "fetched_at": fetched_at.isoformat(),
        "source_age_seconds": int(age),
        "last_success_at": fetched_at.isoformat(),
    }
    registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
    entry["latest_metrics"] = reading.metrics
    entry["latest_units"] = reading.units
    entry["latest_state"] = state
    entry["last_success_at"] = fetched_at.isoformat()
    recovered = int(entry.get("consecutive_failures", 0)) > 0
    entry["consecutive_failures"] = 0
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=reading.metrics,
        units=reading.units,
    )
    append_runtime_event(
        "kaiterra.readings.refreshed",
        entry,
        {
            "device_udid": entry["device_udid"],
            "metric_count": len(reading.metrics),
            "latest_timestamp": reading.latest_timestamp,
        },
    )
    if recovered:
        append_runtime_event("kaiterra.recovered", entry)
    return state


def _setup_error(exc: Exception) -> HTTPException:
    category = exc.category if isinstance(exc, KaiterraError) else "outage"
    if category == "auth":
        return HTTPException(status_code=401, detail="Kaiterra credentials were rejected; update the API key")
    if category in {"provider_contract", "identity_mismatch"}:
        return HTTPException(status_code=422, detail=f"Kaiterra validation failed ({category})")
    if category in {"outage", "quota"}:
        return HTTPException(status_code=503, detail=f"Kaiterra validation temporarily unavailable ({category})")
    return HTTPException(status_code=400, detail="Kaiterra configuration validation failed")


async def refresh_all_entries() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        results.append(await refresh_entry(entry))
    return results
starter.state.provide(refresh_all_entries, source=INTEGRATION_ID)


async def _poll_entry(config_id: str) -> None:
    while True:
        entry = registry.get(config_id)
        if entry is None:
            return
        failures = int(entry.get("consecutive_failures", 0))
        delay = min(int(entry["poll_interval_seconds"]) * (2 ** min(failures, 4)), 3600)
        try:
            await asyncio.sleep(delay)
            await refresh_entry(entry)
        except asyncio.CancelledError:
            raise


async def _stop_config(config_id: str) -> None:
    task = _poll_tasks.pop(config_id, None)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    client = _clients.pop(config_id, None)
    if client:
        await client.close()


async def _activate_config(config_id: str, entry: dict[str, Any], client: KaiterraClient | None) -> None:
    old_task = _poll_tasks.pop(config_id, None)
    old_client = _clients.pop(config_id, None)
    registry.set(config_id, entry)
    if client is not None:
        _clients[config_id] = client
        _poll_tasks[config_id] = asyncio.create_task(_poll_entry(config_id), name=f"kaiterra-poll-{config_id}")
    if old_task:
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)
    if old_client:
        await _close_client_safely(old_client)


async def _close_client_safely(client: KaiterraClient) -> None:
    try:
        await client.close()
    except Exception:
        pass


async def shutdown() -> None:
    for config_id in list(set(_poll_tasks) | set(_clients)):
        await _stop_config(config_id)
