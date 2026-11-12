from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .kaiterra import (
    DEFAULT_BASE_URL,
    KaiterraClient,
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


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    device_udid = resolve_device_udid(config)
    return {
        **identity,
        "host": device_udid,
        "device_udid": device_udid,
        "alias": config.alias or device_udid,
        "base_url": config.base_url or DEFAULT_BASE_URL,
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
        "host": entry["device_udid"],
        "device_udid": entry["device_udid"],
        "alias": entry["alias"],
        "base_url": entry["base_url"],
        "config_id": entry["config_id"],
    }
    if not is_placeholder_api_key(config.api_key):
        state.update(await refresh_entry(entry))
    else:
        registry.update_state(config.id, state, device_id=entry["device_id"])
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {
            "device_udid": entry["device_udid"],
            "alias": entry["alias"],
            "base_url": entry["base_url"],
            "live_api_skipped": is_placeholder_api_key(config.api_key),
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
    if is_placeholder_api_key(config.api_key):
        state = {
            "connected": False,
            "device_udid": entry["device_udid"],
            "reason": "missing_api_key",
        }
        registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
        return state

    client = KaiterraClient(api_key=str(config.api_key), base_url=config.base_url)
    reading = await client.latest_reading(entry["device_udid"])
    metadata = await client.device_metadata(entry["device_udid"])
    state = {
        **reading.metrics,
        "connected": True,
        "device_udid": entry["device_udid"],
        "latest_timestamp": reading.latest_timestamp,
        "name": metadata.get("name") or metadata.get("label") or entry.get("alias"),
        "api_latency_ms": reading.latency_ms,
    }
    registry.update_state(entry["config_id"], state, device_id=entry["device_id"])
    entry["latest_metrics"] = reading.metrics
    entry["latest_units"] = reading.units
    entry["latest_raw"] = reading.raw
    entry["device_metadata"] = metadata
    append_runtime_event(
        "kaiterra.readings.refreshed",
        entry,
        {
            "device_udid": entry["device_udid"],
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
