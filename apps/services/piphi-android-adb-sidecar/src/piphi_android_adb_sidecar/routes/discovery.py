from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
)

from ..contract import CONFIG_SCHEMA

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    # The sidecar must not invent devices before an authenticated ADB transport
    # can return a stable target identity.
    return build_discovery_response([])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
