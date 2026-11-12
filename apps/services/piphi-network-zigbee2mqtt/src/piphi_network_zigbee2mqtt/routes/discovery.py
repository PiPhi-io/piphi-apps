from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..adapter_detector import discover_adapters
from ..contract import CONFIG_SCHEMA

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    adapters = discover_adapters()
    serial_port = inputs.get("serial_port") or (adapters[0].path if adapters else None)
    adapter_hint = inputs.get("adapter") or (adapters[0].adapter_hint if adapters else None)
    return build_discovery_response(
        [
            {
                "id": "zigbee2mqtt-bridge",
                "device_id": "zigbee2mqtt-bridge",
                "host": inputs.get("host", "127.0.0.1"),
                "alias": "Zigbee2MQTT Bridge",
                "serial_port": serial_port,
                "adapter": adapter_hint,
                "detected_adapter_count": len(adapters),
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
