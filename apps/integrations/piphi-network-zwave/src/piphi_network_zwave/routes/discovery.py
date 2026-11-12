from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    return build_discovery_response(
        [
            {
                "id": "demo-device",
                "device_id": "demo-device",
                "host": inputs.get("host", "127.0.0.1"),
                "alias": "Demo Device",
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
