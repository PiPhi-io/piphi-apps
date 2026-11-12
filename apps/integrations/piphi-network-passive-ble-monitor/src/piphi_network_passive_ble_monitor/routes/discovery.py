from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..state import scan_once

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    requested_address = str(inputs.get("host") or "").strip().upper()
    try:
        observations = await scan_once()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="BLE scanner unavailable") from exc
    return build_discovery_response(
        [
            {
                "id": item.address,
                "device_id": item.address,
                "host": item.address,
                "alias": f"BTHome sensor {item.address[-5:]}",
            }
            for item in observations
            if not requested_address or item.address == requested_address
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
