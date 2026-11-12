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
    site_id = inputs.get("site_id")
    return build_discovery_response(
        ([
            {
                "id": f"solaredge-site-{site_id}",
                "device_id": f"solaredge-site-{site_id}",
                "site_id": site_id,
                "alias": f"SolarEdge site {site_id}",
            }
        ] if site_id else [])
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
