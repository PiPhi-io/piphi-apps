from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..tuya import discover_devices

router = APIRouter(tags=["discovery"])


def _validate_discovery_inputs(inputs: dict) -> None:
    cloud_values = [
        inputs.get("api_region") or inputs.get("apiRegion"),
        inputs.get("api_key") or inputs.get("apiKey"),
        inputs.get("api_secret") or inputs.get("apiSecret"),
    ]
    if any(cloud_values) and not all(cloud_values):
        raise HTTPException(
            status_code=422,
            detail="api_region, api_key, and api_secret must all be provided together for cloud discovery",
        )
    if inputs.get("scan_seconds") is not None or inputs.get("scanSeconds") is not None:
        raw_scan_seconds = inputs.get("scan_seconds") or inputs.get("scanSeconds")
        try:
            scan_seconds = int(raw_scan_seconds)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="scan_seconds must be an integer between 1 and 60",
            ) from exc
        if scan_seconds < 1 or scan_seconds > 60:
            raise HTTPException(
                status_code=422,
                detail="scan_seconds must be between 1 and 60",
            )


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    _validate_discovery_inputs(inputs)
    devices = await discover_devices(inputs)
    return build_discovery_response(devices)


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
