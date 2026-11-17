from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import SecretStr

from ..authorization import authorize_runtime_request
from ..source_probe import capture_camera_snapshot
from ..state import get_entry_or_404

router = APIRouter(prefix="/v1/cameras", tags=["camera"])


def require_runtime_access(request: Request) -> None:
    authorize_runtime_request(request, require_configured=True)


def _camera_secret(config_id: str) -> tuple[dict[str, object], SecretStr]:
    entry = get_entry_or_404(config_id)
    source = entry.get("_source_url")
    if not isinstance(source, SecretStr):
        raise TypeError("camera source secret is unavailable")
    return entry, source


@router.get("/{config_id}/source")
async def camera_source(config_id: str, request: Request) -> dict[str, object]:
    require_runtime_access(request)
    entry, source = _camera_secret(config_id)
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


@router.get("/{config_id}/snapshot")
async def camera_snapshot(config_id: str, request: Request) -> Response:
    require_runtime_access(request)
    entry, source = _camera_secret(config_id)
    image = await capture_camera_snapshot(
        source.get_secret_value(),
        preferred_transport=str(entry.get("preferred_transport") or "auto"),
    )
    if image is None:
        raise HTTPException(status_code=502, detail="Camera snapshot is unavailable.")
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
