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
    host = inputs.get("host")
    if not host:
        return build_discovery_response([])
    return build_discovery_response(
        [
            {
                "id": f"reolink-{host}",
                "device_id": f"reolink-{host}",
                "host": host,
                "alias": "Reolink camera or NVR",
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
