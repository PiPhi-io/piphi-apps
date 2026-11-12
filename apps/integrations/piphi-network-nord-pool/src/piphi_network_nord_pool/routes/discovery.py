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
    # A market area is selected by the user; it is not a LAN-discovered device.
    area = inputs.get("market_area")
    if not area:
        return build_discovery_response([])
    return build_discovery_response(
        [{"id": str(area), "device_id": str(area), "market_area": str(area)}]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
