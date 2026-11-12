from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from piphi_runtime_kit_python import (
    build_local_event_record,
    build_runtime_identity,
    create_runtime_starter,
)

from .contract import CAPABILITIES, COMMANDS
from .bridge_models import MqttSettings, SerialSettings, SidecarStore, Zigbee2MqttBridgeConfig
from .config_renderer import render_zigbee2mqtt_config
from .config_store import write_config_atomic
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
sidecar_store = SidecarStore()


def make_entry(config: DeviceConfig) -> dict[str, Any]:
    identity = build_runtime_identity(config, integration_id=INTEGRATION_ID)
    return {
        **identity,
        "host": config.host,
        "alias": config.alias,
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
    registry.update_state(
        config.id,
        {
            "connected": True,
            "zigbee_network_topology": (
                sidecar_store.last_network_map.model_dump(mode="json", exclude={"server"})
                if sidecar_store.last_network_map
                else None
            ),
            "host": config.host,
            "alias": config.alias,
            "config_id": entry["config_id"],
        },
        device_id=entry["device_id"],
    )
    append_runtime_event(
        "runtime.config.applied",
        entry,
        {"host": config.host, "alias": config.alias},
    )
    if config.serial_port:
        bridge_config = Zigbee2MqttBridgeConfig(
            mqtt=MqttSettings(server=config.mqtt_server, base_topic=config.mqtt_base_topic),
            serial=SerialSettings(port=config.serial_port, adapter=config.adapter),
            data_path=config.data_path,
        )
        rendered = render_zigbee2mqtt_config(bridge_config)
        target_path = f"{bridge_config.data_path.rstrip('/')}/configuration.yaml"
        try:
            write_result = write_config_atomic(rendered.yaml, target_path)
        except OSError as exc:
            sidecar_store.last_error = f"Could not write Zigbee2MQTT configuration: {exc}"
            raise HTTPException(status_code=500, detail=sidecar_store.last_error) from exc

        rendered.config_path = write_result.config_path
        rendered.config_hash = write_result.config_hash
        sidecar_store.current_config = bridge_config
        sidecar_store.current_render = rendered
        sidecar_store.config_path = write_result.config_path
        sidecar_store.config_hash = write_result.config_hash
        sidecar_store.last_error = None


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
