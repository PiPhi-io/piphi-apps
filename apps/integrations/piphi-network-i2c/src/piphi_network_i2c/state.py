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
    schedule_telemetry_delivery,
    validate_typed_configs,
)

from .sensors import SensorConfig, discover_devices, hardware_diagnostics, normalize_config, read_state

INTEGRATION_ID = "piphi-network-i2c"
INTEGRATION_NAME = "PiPhi Network I2C Sensors"
INTEGRATION_VERSION = "0.1.1"

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text())
UI_CONFIG_SCHEMA = {
    "fields": [
        {"name": "adapter", "label": "Adapter", "type": "select", "required": True, "options": ["linux_i2c", "mcp2221a", "ft232h", "mock"], "default": "linux_i2c"},
        {"name": "bus", "label": "I2C Bus", "type": "number", "required": True, "default": 1},
        {"name": "address", "label": "Address", "type": "text", "required": False, "placeholder": "0x76"},
        {"name": "sensor_model", "label": "Sensor Model", "type": "select", "required": True, "options": ["auto", "bme680", "bme280", "bmp280", "aht20", "pmsa003i", "generic"], "default": "auto"},
        {"name": "alias", "label": "Alias", "type": "text", "required": False},
        {"name": "poll_interval_seconds", "label": "Poll Interval", "type": "number", "required": True, "default": 30},
    ]
}


class I2CSensorRuntimeConfig(RuntimeConfig):
    adapter: str = "linux_i2c"
    bus: int = 1
    address: str | int | None = None
    sensor_model: str = "auto"
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
telemetry_client = starter.telemetry_client
capabilities = MANIFEST.get("capabilities", {})
commands = MANIFEST.get("commands", {})

TELEMETRY_UNITS = {
    key: value["unit"]
    for key, value in capabilities.items()
    if isinstance(value, dict) and value.get("kind") == "sensor" and value.get("unit")
}


def config_to_sensor_config(config: I2CSensorRuntimeConfig) -> SensorConfig:
    return normalize_config(config.model_dump())


def typed_snapshot_configs(snapshot: RuntimeConfigSnapshot) -> list[I2CSensorRuntimeConfig]:
    return validate_typed_configs(
        [
            config.model_dump() if hasattr(config, "model_dump") else config
            for config in snapshot.configs
        ],
        I2CSensorRuntimeConfig,
    )


def primary_config() -> I2CSensorRuntimeConfig:
    entry = registry.primary_entry()
    if entry is None:
        return I2CSensorRuntimeConfig(id="i2c-dev", adapter="linux_i2c")
    return I2CSensorRuntimeConfig.model_validate(entry["config"])


def get_entry_or_404(config_id: str) -> dict[str, Any]:
    entry = registry.get(config_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown config_id={config_id}")
    return entry


def entry_for_config(config: I2CSensorRuntimeConfig) -> dict[str, Any]:
    sensor_config = config_to_sensor_config(config)
    try:
        devices = discover_devices(sensor_config)
    except Exception:
        devices = []
    device = devices[0] if devices else {
        "id": config.device_id or config.id,
        "name": config.alias or "I2C Sensor",
        "device_id": config.device_id or config.id,
        "adapter": sensor_config.adapter,
        "bus": sensor_config.bus,
        "model": sensor_config.sensor_model,
    }
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    device_id = config.device_id or device.get("device_id") or identity["device_id"]
    return {
        **identity,
        "device_id": device_id,
        "name": config.alias or device.get("name") or "I2C Sensor",
        "config": config.model_dump(),
        "device": device,
    }


def entity_for_entry(entry: dict[str, Any]) -> dict[str, Any]:
    device = entry.get("device") if isinstance(entry.get("device"), dict) else {}
    model = str(device.get("model") or "").lower()
    entity_capabilities = ["connected", "temperature_c", "humidity_percent", "pressure_hpa", "refresh"]
    if model == "bme680":
        entity_capabilities.append("gas_ohms")
    elif model == "pmsa003i":
        entity_capabilities = [
            "connected",
            "pm1_0_standard_ugm3",
            "pm2_5_standard_ugm3",
            "pm10_standard_ugm3",
            "pm1_0_env_ugm3",
            "pm2_5_env_ugm3",
            "pm10_env_ugm3",
            "particles_0_3um_per_0_1l",
            "particles_0_5um_per_0_1l",
            "particles_1_0um_per_0_1l",
            "particles_2_5um_per_0_1l",
            "particles_5_0um_per_0_1l",
            "particles_10um_per_0_1l",
            "refresh",
        ]
    return {
        "id": str(device.get("id") or entry["config_id"]),
        "name": str(entry.get("name") or device.get("name") or "I2C Sensor"),
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


def schedule_state_telemetry(entry: dict[str, Any], state: dict[str, Any]) -> None:
    metrics = {
        key: value
        for key, value in state.items()
        if key not in {"error", "sampled_at"}
        and isinstance(value, (bool, int, float, str))
    }
    if not metrics:
        return
    schedule_telemetry_delivery(
        process_state=runtime.process_state,
        telemetry_client=telemetry_client,
        auth_context=runtime.auth,
        config_id=str(entry["config_id"]),
        device_id=str(entry["device_id"]),
        container_id=entry.get("container_id"),
        metrics=metrics,
        units={key: TELEMETRY_UNITS[key] for key in metrics if key in TELEMETRY_UNITS},
        timestamp=str(state.get("sampled_at")) if state.get("sampled_at") else None,
    )


async def apply_config(config: I2CSensorRuntimeConfig) -> None:
    entry = entry_for_config(config)
    registry.set(config.id, entry)
    try:
        state = read_state(config_to_sensor_config(config))
    except Exception as exc:
        state = {"connected": False, "error": str(exc)}
    registry.update_state(config.id, state, device_id=entry["device_id"])
    schedule_state_telemetry(entry, state)
    append_runtime_event("i2c.config.applied", entry, {"sensor_model": config.sensor_model})


async def remove_config(config_id: str) -> bool:
    entry = registry.remove(config_id)
    if entry is None:
        return False
    append_runtime_event("i2c.config.removed", entry)
    return True


def read_current_state() -> dict[str, Any]:
    if not registry.ids():
        config = primary_config()
        try:
            return {"state": read_state(config_to_sensor_config(config))}
        except Exception as exc:
            return {"state": {"connected": False, "error": str(exc)}}
    return {"entries": registry.entries, "state_snapshots": registry.state_snapshots}


def refresh_state_for_config(config: I2CSensorRuntimeConfig) -> dict[str, Any]:
    state_payload = read_state(config_to_sensor_config(config))
    registry.update_state(config.id, state_payload)
    return state_payload


def refresh_all_state() -> None:
    for config_id in registry.ids():
        entry = get_entry_or_404(config_id)
        refresh_state_for_config(I2CSensorRuntimeConfig.model_validate(entry["config"]))


starter.state.provide(refresh_all_state, source=INTEGRATION_ID)


def diagnostics_payload() -> dict[str, Any]:
    return {
        "active_config_ids": registry.ids(),
        "recent_event_count": len(registry.recent_events),
        "supported_models": ["bme680", "bme280", "bmp280", "aht20", "pmsa003i", "generic"],
        "hardware": hardware_diagnostics(),
    }
