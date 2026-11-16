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
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .weatherxm import (
    DEFAULT_WEATHERXM_BASE_URL,
    WeatherXMClient,
    WeatherXMError,
    device_display_name,
    has_credentials,
    resolve_station_id,
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

capabilities = CAPABILITIES
commands = COMMANDS
API_STANDING = "unofficial_unsupported_mobile_account_api"
PRODUCTION_PUBLICATION_ALLOWED = False
MAX_SOURCE_AGE_SECONDS = 1800
_clients: dict[str, WeatherXMClient] = {}
_poll_tasks: dict[str, asyncio.Task[None]] = {}


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    station_id = resolve_station_id(config)
    return {
        **identity,
        "host": station_id,
        "station_id": station_id,
        "alias": config.alias or station_id or "WeatherXM Station",
        "base_url": config.base_url or DEFAULT_WEATHERXM_BASE_URL,
        "config": config.model_dump(exclude={"api_token", "username", "password"}),
        "poll_interval_seconds": config.poll_interval_seconds,
        "api_standing": API_STANDING,
        "production_publication_allowed": PRODUCTION_PUBLICATION_ALLOWED,
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
    if current and current.get("station_id") != entry["station_id"]:
        raise HTTPException(status_code=409, detail="station_id is immutable; create a new configuration")
    if any(
        other.get("station_id") == entry["station_id"] and other.get("config_id") != config.id
        for other in registry.entries.values()
    ):
        raise HTTPException(status_code=409, detail="station_id is already configured")
    state = {
        "connected": False,
        "station_id": entry["station_id"],
        "alias": entry["alias"],
        "base_url": entry["base_url"],
        "config_id": entry["config_id"],
        "api_standing": API_STANDING,
        "production_publication_allowed": PRODUCTION_PUBLICATION_ALLOWED,
    }
    if has_credentials(config):
        candidate = WeatherXMClient(
            api_token=config.api_token,
            username=config.username,
            password=config.password,
            base_url=config.base_url,
        )
        try:
            reading = await _read_provider(candidate, entry)
        except Exception as exc:
            await _close_client_safely(candidate)
            raise _setup_error(exc) from None
        await _activate_config(config.id, entry, candidate)
        state.update(_publish_success(entry, reading))
    else:
        if current and config.id in _clients:
            raise HTTPException(status_code=400, detail="credentials are required to replace an active configuration")
        await _activate_config(config.id, entry, None)
        state["reason"] = "missing_weatherxm_credentials"
        registry.update_state(config.id, state, device_id=entry["device_id"])
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {
            "station_id": entry["station_id"],
            "alias": entry["alias"],
            "base_url": entry["base_url"],
            "live_api_skipped": not has_credentials(config),
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
    station_id = str(entry["station_id"])
    client = _clients.get(entry["config_id"])
    if client is None:
        state = {
            "connected": False,
            "station_id": station_id,
            "reason": "missing_weatherxm_credentials",
            "api_standing": API_STANDING,
            "production_publication_allowed": PRODUCTION_PUBLICATION_ALLOWED,
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state

    fetched_at = datetime.now(UTC)
    try:
        reading = await _read_provider(client, entry)
    except Exception as exc:
        category = exc.category if isinstance(exc, WeatherXMError) else "outage"
        first_failure = int(entry.get("consecutive_failures", 0)) == 0
        previous = dict(entry.get("latest_state") or {})
        state = {
            **previous,
            "connected": False,
            "available": False,
            "stale": True,
            "station_id": station_id,
            "error_class": category,
            "last_success_at": entry.get("last_success_at"),
            "api_standing": API_STANDING,
            "production_publication_allowed": PRODUCTION_PUBLICATION_ALLOWED,
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        if first_failure:
            append_runtime_event("weatherxm.unavailable", entry, {"error_class": category})
        return state
    return _publish_success(entry, reading, fetched_at=fetched_at)


async def _read_provider(client: WeatherXMClient, entry: dict[str, Any]):
    reading = await client.latest_reading(str(entry["station_id"]))
    resolved_station_id = str(reading.device.get("id") or "")
    if resolved_station_id != entry["station_id"]:
        raise WeatherXMError("identity_mismatch")
    return reading


def _publish_success(entry: dict[str, Any], reading, *, fetched_at: datetime | None = None) -> dict[str, Any]:
    fetched_at = fetched_at or datetime.now(UTC)
    station_id = str(entry["station_id"])
    resolved_station_id = str(reading.device["id"])
    source_age = max(0.0, (fetched_at - reading.observed_at).total_seconds())
    stale = source_age > MAX_SOURCE_AGE_SECONDS
    state = {
        **reading.metrics,
        "connected": True,
        "available": not stale,
        "stale": stale,
        "station_id": resolved_station_id,
        "latest_timestamp": reading.latest_timestamp,
        "name": device_display_name(reading.device, entry["alias"]),
        "relation": reading.device.get("relation"),
        "timezone": reading.device.get("timezone"),
        "api_latency_ms": reading.latency_ms,
        "source_observed_at": reading.observed_at.isoformat(),
        "source_age_seconds": int(source_age),
        "fetched_at": fetched_at.isoformat(),
        "last_success_at": fetched_at.isoformat(),
        "api_standing": API_STANDING,
        "production_publication_allowed": PRODUCTION_PUBLICATION_ALLOWED,
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
        "weatherxm.readings.refreshed",
        entry,
        {
            "station_id": resolved_station_id,
            "metric_count": len(reading.metrics),
            "latest_timestamp": reading.latest_timestamp,
        },
    )
    if recovered:
        append_runtime_event("weatherxm.recovered", entry)
    return state


def _setup_error(exc: Exception) -> HTTPException:
    category = exc.category if isinstance(exc, WeatherXMError) else "outage"
    if category == "auth":
        return HTTPException(status_code=401, detail="WeatherXM credentials were rejected; update account credentials")
    if category in {"provider_contract", "identity_mismatch"}:
        return HTTPException(status_code=422, detail=f"WeatherXM validation failed ({category})")
    if category in {"outage", "quota"}:
        return HTTPException(status_code=503, detail=f"WeatherXM validation temporarily unavailable ({category})")
    return HTTPException(status_code=400, detail="WeatherXM configuration validation failed")


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


async def _activate_config(config_id: str, entry: dict[str, Any], client: WeatherXMClient | None) -> None:
    old_task = _poll_tasks.pop(config_id, None)
    old_client = _clients.pop(config_id, None)
    registry.set(config_id, entry)
    if client is not None:
        _clients[config_id] = client
        _poll_tasks[config_id] = asyncio.create_task(_poll_entry(config_id), name=f"weatherxm-poll-{config_id}")
    if old_task:
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)
    if old_client:
        await _close_client_safely(old_client)


async def _close_client_safely(client: WeatherXMClient) -> None:
    try:
        await client.close()
    except Exception:
        pass


async def shutdown() -> None:
    for config_id in list(set(_poll_tasks) | set(_clients)):
        await _stop_config(config_id)
