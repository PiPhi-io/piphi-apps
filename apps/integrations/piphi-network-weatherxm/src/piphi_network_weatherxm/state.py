from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .schemas import DeviceConfig
from .settings import INTEGRATION_ID, INTEGRATION_NAME, INTEGRATION_VERSION
from .weatherxm import (
    DEFAULT_WEATHERXM_BASE_URL,
    WeatherXMClient,
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


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    station_id = resolve_station_id(config)
    return {
        **identity,
        "host": station_id,
        "station_id": station_id,
        "alias": config.alias or station_id or "WeatherXM Station",
        "base_url": config.base_url or DEFAULT_WEATHERXM_BASE_URL,
        "config": config.model_dump(),
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
    registry.set(config.id, entry)
    state = {
        "connected": False,
        "station_id": entry["station_id"],
        "alias": entry["alias"],
        "base_url": entry["base_url"],
        "config_id": entry["config_id"],
    }
    if has_credentials(config):
        state.update(await refresh_entry(entry))
    else:
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
    config = DeviceConfig.model_validate(entry["config"])
    station_id = resolve_station_id(config)
    if not has_credentials(config):
        state = {
            "connected": False,
            "station_id": station_id,
            "reason": "missing_weatherxm_credentials",
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state

    client = WeatherXMClient(
        api_token=config.api_token,
        username=config.username,
        password=config.password,
        base_url=config.base_url,
    )
    reading = await client.latest_reading(station_id or None)
    resolved_station_id = str(reading.device.get("id") or station_id or entry["device_id"])
    state = {
        **reading.metrics,
        "connected": True,
        "station_id": resolved_station_id,
        "latest_timestamp": reading.latest_timestamp,
        "name": device_display_name(reading.device, entry["alias"]),
        "relation": reading.device.get("relation"),
        "timezone": reading.device.get("timezone"),
        "api_latency_ms": reading.latency_ms,
    }
    registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
    entry["station_id"] = resolved_station_id
    entry["latest_metrics"] = reading.metrics
    entry["latest_units"] = reading.units
    entry["latest_raw"] = reading.raw
    append_runtime_event(
        "weatherxm.readings.refreshed",
        entry,
        {
            "station_id": resolved_station_id,
            "metric_count": len(reading.metrics),
            "latest_timestamp": reading.latest_timestamp,
        },
    )
    return state


async def refresh_all_entries() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        results.append(await refresh_entry(entry))
    return results
starter.state.provide(refresh_all_entries, source=INTEGRATION_ID)
