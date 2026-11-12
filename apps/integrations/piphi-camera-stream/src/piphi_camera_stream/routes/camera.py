from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import SecretStr

from ..state import get_entry_or_404

router = APIRouter(prefix="/v1/cameras", tags=["camera"])


@router.get("/{config_id}/source")
async def camera_source(config_id: str, request: Request) -> dict[str, object]:
    expected_token = (os.getenv("PIPHI_INTEGRATION_INTERNAL_TOKEN") or "").strip()
    expected_container_id = (os.getenv("PIPHI_CONTAINER_ID") or "").strip()
    provided_token = request.headers.get("X-PiPhi-Integration-Token", "").strip()
    provided_container_id = request.headers.get("X-Container-Id", "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Camera source access is not configured.",
        )
    if not hmac.compare_digest(provided_token, expected_token) or (
        expected_container_id
        and not hmac.compare_digest(provided_container_id, expected_container_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid runtime credentials.",
        )
    entry = get_entry_or_404(config_id)
    source = entry.get("_source_url")
    if not isinstance(source, SecretStr):
        raise RuntimeError("camera source secret is unavailable")
    return {
        "contract_version": "camera.media.v1",
        "message_type": "camera.source",
        "audience": "core-sidecar",
        "camera_id": str(entry["device_id"]),
        "source_url": source.get_secret_value(),
        "source_protocol": str(entry["source_protocol"]),
        "preferred_transport": str(entry["preferred_transport"]),
        "connect_timeout_seconds": 10,
    }
