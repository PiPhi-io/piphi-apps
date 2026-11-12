from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    IntegrationDiscoveryResponse,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..sensors import discover_devices, normalize_config

router = APIRouter(tags=["discovery"])


@router.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(payload: IntegrationDiscoveryRequest | None = None) -> IntegrationDiscoveryResponse:
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    config = normalize_config({**inputs, "adapter": inputs.get("adapter") or "linux_spi"})
    try:
        devices = discover_devices(config)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_discovery_response(devices)
