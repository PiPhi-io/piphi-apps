from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..settings import DEFAULT_MQTT_BASE_TOPIC, DEFAULT_SIDECAR_BASE_URL
from ..sidecar_client import SidecarUnavailable, Zigbee2MqttSidecarClient
from ..zigbee_devices import normalize_zigbee2mqtt_device

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    sidecar_base_url = str(inputs.get("sidecar_base_url") or DEFAULT_SIDECAR_BASE_URL)
    devices = _devices_from_inputs(inputs, sidecar_base_url=sidecar_base_url)
    if not devices:
        client = Zigbee2MqttSidecarClient(sidecar_base_url)
        try:
            devices = await client.devices()
        except SidecarUnavailable:
            devices = []
    return build_discovery_response(devices)


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA


def _devices_from_inputs(inputs: dict, *, sidecar_base_url: str) -> list[dict]:
    raw_devices = inputs.get("devices")
    if isinstance(raw_devices, list):
        return [
            normalize_zigbee2mqtt_device(
                device,
                default_base_topic=str(inputs.get("mqtt_base_topic") or DEFAULT_MQTT_BASE_TOPIC),
                sidecar_base_url=sidecar_base_url,
            )
            for device in raw_devices
            if isinstance(device, dict)
        ]

    if isinstance(inputs.get("device"), dict):
        return [
            normalize_zigbee2mqtt_device(
                inputs["device"],
                default_base_topic=str(inputs.get("mqtt_base_topic") or DEFAULT_MQTT_BASE_TOPIC),
                sidecar_base_url=sidecar_base_url,
            )
        ]

    if inputs.get("friendly_name") or inputs.get("ieee_address"):
        return [
            normalize_zigbee2mqtt_device(
                inputs,
                default_base_topic=str(inputs.get("mqtt_base_topic") or DEFAULT_MQTT_BASE_TOPIC),
                sidecar_base_url=sidecar_base_url,
            )
        ]
    return []
