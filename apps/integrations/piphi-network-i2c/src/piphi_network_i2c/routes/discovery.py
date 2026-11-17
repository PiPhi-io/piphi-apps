from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    IntegrationDiscoveryResponse,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..sensors import discover_devices, normalize_config, preflight_target
from ..state import classify_hardware_error, run_hardware_operation

router = APIRouter(tags=["discovery"])


@router.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(payload: IntegrationDiscoveryRequest | None = None) -> IntegrationDiscoveryResponse:
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    try:
        config = normalize_config(
            {
                **inputs,
                "adapter": inputs.get("adapter") or "linux_i2c",
                "allow_scan": inputs.get("allow_scan") is True,
            }
        )
        preflight_target(config)
        devices = await run_hardware_operation(config, discover_devices)
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"I2C discovery preflight failed: {classify_hardware_error(exc)}",
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_discovery_response(devices)
