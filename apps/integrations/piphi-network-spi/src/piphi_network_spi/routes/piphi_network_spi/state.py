from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from piphi_runtime_kit_python import (
    RuntimeConfig,
    RuntimeConfigSnapshot,
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
    validate_typed_configs,
)

from .sensors import SensorConfig, discover_devices, hardware_diagnostics, normalize_config, read_state

INTEGRATION_ID = "piphi-network-spi"
INTEGRATION_NAME = "PiPhi Network SPI Sensors"
INTEGRATION_VERSION = "0.1.1"

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
UI_CONFIG_SCHEMA = {
    "fields": [
        {"name": "adapter", "label": "Adapter", "type": "select", "required": True, "options": ["linux_spi", "ft232h", "mock"], "default": "linux_spi"},
        {"name": "bus", "label": "SPI Bus", "type": "number", "required": True, "default": 0},
        {"name": "chip_select", "label": "Chip Select", "type": "number", "required": True, "default": 0},
        {"name": "sensor_model", "label": "Sensor Model", "type": "select", "required": True, "options": ["auto", "bme680", "bme280", "bmp280"], "default": "auto"},
        {"name": "alias", "label": "Alias", "type": "text", "required": False},
        {"name": "baudrate", "label": "Baudrate", "type": "number", "required": True, "default": 100000},
        {"name": "poll_interval_seconds", "label": "Poll Interval", "type": "number", "required": True, "default": 30},
    ]
}


class SPISensorRuntimeConfig(RuntimeConfig):
    adapter: str = "linux_spi"
    bus: int = 0
    chip_select: int = 0
    sensor_model: str = "auto"
    baudrate: int = 100000
    poll_interval_seconds: int = 30
    alias: str | None = None


starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
config_sync = starter.config_sync
capabilities = MANIFEST.get("capabilities", {})
commands = MANIFEST.get("commands", {})


def config_to_sensor_config(config: SPISensorRuntimeConfig) -> SensorConfig:
    return normalize_config(config.model_dump())


def typed_snapshot_configs(snapshot: RuntimeConfigSnapshot) -> list[SPISensorRuntimeConfig]:
    return validate_typed_configs(
        [
            config.model_dump() if hasattr(config, "model_dump") else config
            for config in snapshot.configs
        ],
        SPISensorRuntimeConfig,
    )


def primary_config() -> SPISensorRuntimeConfig:
    entry = registry.primary_entry()
    if entry is None:
        return SPISensorRuntimeConfig(id="spi-dev", adapter="linux_spi")
    return SPISensorRuntimeConfig.model_validate(entry["config"])


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def entry_for_config(config: SPISensorRuntimeConfig) -> dict[str, Any]:
    sensor_config = config_to_sensor_config(config)
    device = discover_devices(sensor_config)[0]
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "device_id": config.device_id or device.get("device_id") or identity["device_id"],
        "name": config.alias or device.get("name") or "SPI Sensor",
        "config": config.model_dump(),
        "device": device,
    }


def entity_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    device = entry.get("device") if isinstance(entry.get("device"), dict) else {}
    model = str(device.get("model") or "").lower()
    entity_capabilities = ["connected", "temperature_c", "humidity_percent", "pressure_hpa", "refresh"]
    if model == "bme680":
        entity_capabilities.append("gas_ohms")
    return {
        "id": str(device.get("id") or entry["config_id"]),
        "name": str(entry.get("name") or device.get("name") or "SPI Sensor"),
        "config_id": entry["config_id"],
        "device_id": entry["device_id"],
        "device_class": "environmental_sensor",
        "entity_type": "sensor",
        "capabilities": entity_capabilities,
        "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
        "dashboard": {
            "allowed_widgets": ["sensor-card", "stat", "line-chart", "air-quality-card", "room-climate-card"],
            "default_widget": "sensor-card",
        },
        "metadata": device,
    }


def append_runtime_event(
    event_type: str,
    entry: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = build_local_event_record(
        event_type=event_type,
        device=entry,
        payload=payload or {},
        source=INTEGRATION_ID,
        severity="info",
    )
    registry.append_event(event)
    return event


async def apply_config(config: SPISensorRuntimeConfig) -> None:
    entry = entry_for_config(config)
    registry.set(config.id, entry)
    try:
        state = read_state(config_to_sensor_config(config))
    except Exception as exc:
        state = {"connected": False, "error": str(exc)}
    registry.update_state(config.id, state, device_id=entry["device_id"])
    append_runtime_event("spi.config.applied", entry, {"sensor_model": config.sensor_model})


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event("spi.config.removed", entry)
    return True


def read_current_state() -> dict[str, Any]:
    if not registry.ids():
        config = primary_config()
        try:
            return {"state": read_state(config_to_sensor_config(config))}
        except Exception as exc:
            return {"state": {"connected": False, "error": str(exc)}}
    return {"entries": registry.entries, "state_snapshots": registry.state_snapshots}


def diagnostics_payload() -> dict[str, Any]:
    return {
        "active_config_ids": registry.ids(),
        "recent_event_count": len(registry.recent_events),
        "supported_models": ["bme680", "bme280", "bmp280"],
        "hardware": hardware_diagnostics(),
    }
