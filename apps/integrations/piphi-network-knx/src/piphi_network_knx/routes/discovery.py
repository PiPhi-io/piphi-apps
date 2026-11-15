from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..protocol import discover_gateways

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None) -> Any:
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    try:
        gateways = await discover_gateways(inputs.get("local_ip"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="KNX/IP discovery failed") from exc
    return build_discovery_response(gateways)


@router.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return CONFIG_SCHEMA
