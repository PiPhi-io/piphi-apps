from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
)

from ..contract import CONFIG_SCHEMA

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(_payload: IntegrationDiscoveryRequest | None = None):
    return build_discovery_response([])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
