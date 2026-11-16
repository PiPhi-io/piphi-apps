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
    requested_udid = inputs.get("device_udid") or inputs.get("host")
    if not requested_udid:
        return build_discovery_response([])
    return build_discovery_response([{
        "id": str(requested_udid),
        "device_id": str(requested_udid),
        "host": str(requested_udid),
        "device_udid": str(requested_udid),
        "alias": inputs.get("alias", "Kaiterra device"),
    }])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
