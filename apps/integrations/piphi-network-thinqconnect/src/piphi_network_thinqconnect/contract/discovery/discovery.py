from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    build_discovery_response,
    format_discovery_attempt_log,
    normalize_discovery_inputs,
)

from piphi_network_thinqconnect.lib.client import ThinQApiClient, ThinQClientError
from piphi_network_thinqconnect.lib.logging import logger
from piphi_network_thinqconnect.lib.schemas import ThinQDiscoveryRequest
from piphi_network_thinqconnect.lib.simulator import SimulatedThinQClient


router = APIRouter(tags=["discovery"])
thinq_client = ThinQApiClient()
simulator_client = SimulatedThinQClient()


async def _run_discovery(
    *,
    access_token: str | None = None,
    country_code: str | None = None,
    client_id: str | None = None,
    simulation_mode: bool = False,
) -> dict:
    normalized_inputs = normalize_discovery_inputs(
        {
            "access_token": access_token,
            "country_code": country_code,
            "client_id": client_id,
        }
    )
    logger.info(format_discovery_attempt_log(inputs=normalized_inputs))

    resolved_access_token = str(normalized_inputs.get("access_token") or "").strip()
    resolved_country_code = str(normalized_inputs.get("country_code") or "").strip().upper()
    resolved_client_id = str(normalized_inputs.get("client_id") or "").strip() or None

    if not simulation_mode and (not resolved_access_token or not resolved_country_code):
        return build_discovery_response([]).model_dump()

    try:
        upstream_client = simulator_client if simulation_mode else thinq_client
        devices = await upstream_client.discover_devices(
            access_token=resolved_access_token,
            country_code=resolved_country_code,
            client_id=resolved_client_id,
        )
    except ThinQClientError as exc:
        raise HTTPException(status_code=500, detail=f"ThinQ discovery failed: {exc}") from exc

    return build_discovery_response(devices).model_dump()


@router.get("/discover")
@router.get("/discovery")
async def get_discovered_devices() -> dict:
    return await _run_discovery()


@router.post("/discover")
@router.post("/discovery")
async def discover_devices_with_inputs(request: ThinQDiscoveryRequest) -> dict:
    return await _run_discovery(
        access_token=request.access_token,
        country_code=request.country_code,
        client_id=request.client_id,
        simulation_mode=request.simulation_mode,
    )
