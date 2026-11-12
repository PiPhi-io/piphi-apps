from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None) -> Any:
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    simulated = bool(inputs.get("simulation_mode"))
    host = (
        "simulated-pfsense.local"
        if simulated
        else str(inputs.get("host") or "pfsense.local")
    )
    return build_discovery_response(
        [
            {
                "id": host,
                "device_id": host,
                "host": host,
                "alias": "Simulated pfSense Home" if simulated else "pfSense Firewall",
                "simulation_mode": simulated,
                "discovery_method": "simulator" if simulated else "user_supplied_host",
            }
        ]
    )


@router.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return CONFIG_SCHEMA
