import logging

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..state import runtime_data
from ..tapo_client import TapoSetupError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    required = {key: str(inputs.get(key) or "").strip() for key in ("host", "username", "password")}
    if not all(required.values()):
        return build_discovery_response([])
    try:
        client = await runtime_data.connector(**required)
        snapshot = await client.refresh()
    except TapoSetupError as exc:
        raise HTTPException(status_code=422, detail={"error": exc.code}) from exc
    finally:
        if "client" in locals():
            try:
                await client.close()
            except Exception as cleanup_exc:  # noqa: BLE001 - third-party cleanup
                logger.debug(
                    "tapo_discovery_disconnect_failed error=%s",
                    type(cleanup_exc).__name__,
                )
    return build_discovery_response([{"id": snapshot["hardware_id"], "device_id": snapshot["hardware_id"], "alias": snapshot["name"], "model": snapshot["model"]}])


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
