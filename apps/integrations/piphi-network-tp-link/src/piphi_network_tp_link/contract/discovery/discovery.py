from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, SecretStr
from piphi_runtime_kit_python import (
    build_discovery_response,
    format_discovery_attempt_log,
    normalize_discovery_inputs,
)

from piphi_network_tp_link.lib.kasa_client import discover_devices
from piphi_network_tp_link.lib.logging import logger


router = APIRouter(tags=["discovery"])


class DiscoveryRequest(BaseModel):
    host: str | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None


async def _run_discovery(
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict:
    normalized_inputs = normalize_discovery_inputs(
        {
            "host": host,
            "username": username,
            "password": password,
        }
    )
    logger.info(format_discovery_attempt_log(inputs=normalized_inputs))

    try:
        discover_kwargs = {
            "username": normalized_inputs.get("username"),
            "password": normalized_inputs.get("password"),
        }
        if normalized_inputs.get("host"):
            discover_kwargs["host"] = normalized_inputs["host"]
        devices = await discover_devices(**discover_kwargs)
    except Exception as exc:
        logger.warning("kasa_discovery_failed error=%s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Discovery failed") from exc

    return build_discovery_response(devices).model_dump()


@router.get("/discover")
@router.get("/discovery")
async def get_discovered_devices() -> dict:
    return await _run_discovery()


@router.post("/discover")
@router.post("/discovery")
async def discover_devices_with_inputs(request: DiscoveryRequest) -> dict:
    return await _run_discovery(
        host=request.host,
        username=request.username.get_secret_value() if request.username else None,
        password=request.password.get_secret_value() if request.password else None,
    )
