from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..midea_client import MideaLanClient, MideaSetupError

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    host = str(inputs.get("host") or "").strip()
    if not host:
        return build_discovery_response([])
    token = str(inputs.get("token") or "").strip() or None
    key = str(inputs.get("key") or "").strip() or None
    raw_device_id = inputs.get("midea_device_id")
    try:
        device_id = int(raw_device_id) if raw_device_id not in (None, "") else None
        client = await MideaLanClient.connect(
            host=host,
            port=int(inputs.get("port") or 6444),
            device_id=device_id,
            token=token,
            key=key,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_discovery_input"}) from exc
    except MideaSetupError as exc:
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    try:
        return build_discovery_response(
            [
                {
                    "id": client.hardware_id,
                    "device_id": client.hardware_id,
                    "host": host,
                    "alias": "Midea air conditioner",
                }
            ]
        )
    finally:
        await client.close()


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
