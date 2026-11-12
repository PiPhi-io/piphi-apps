from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..kaiterra import TEST_LASER_EGG_UDID, TEST_SENSEDGE_UDID

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    requested_udid = inputs.get("device_udid") or inputs.get("host")
    return build_discovery_response(
        [
            {
                "id": str(requested_udid or TEST_SENSEDGE_UDID),
                "device_id": str(requested_udid or TEST_SENSEDGE_UDID),
                "host": str(requested_udid or TEST_SENSEDGE_UDID),
                "device_udid": str(requested_udid or TEST_SENSEDGE_UDID),
                "alias": inputs.get("alias", "Kaiterra Sensedge"),
            },
            {
                "id": TEST_LASER_EGG_UDID,
                "device_id": TEST_LASER_EGG_UDID,
                "host": TEST_LASER_EGG_UDID,
                "device_udid": TEST_LASER_EGG_UDID,
                "alias": "Kaiterra Laser Egg",
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
