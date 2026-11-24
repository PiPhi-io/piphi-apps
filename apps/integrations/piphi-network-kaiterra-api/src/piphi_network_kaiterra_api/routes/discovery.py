from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..state import device_ref
router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    requested_udid = str(inputs.get("device_udid") or "").strip()
    if not requested_udid:
        return build_discovery_response([])
    from uuid import UUID
    try:
        requested_udid = str(UUID(requested_udid))
    except ValueError:
        return build_discovery_response([])
    ref = device_ref(requested_udid)
    return build_discovery_response([{
        "id": ref,
        "device_id": ref,
        "device_ref": ref,
        "alias": inputs.get("alias", "Kaiterra device"),
    }])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
