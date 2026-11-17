from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ..authorization import authorize_sidecar_request
from ..contract import CAMERA_MEDIA_CONTRACT_VERSION
from ..go2rtc import Go2RtcError, validate_source_url
from ..media_sessions import (
    CameraMediaCapacityError,
    CameraSourceUnavailableError,
    media_session_broker,
)

MAX_SDP_BYTES = 256 * 1024
logger = logging.getLogger(__name__)


def require_camera_media_authorization(request: Request) -> None:
    authorize_sidecar_request(request)


router = APIRouter(
    prefix="/v1/camera-media",
    tags=["camera-media-service"],
    dependencies=[Depends(require_camera_media_authorization)],
)


class ClosedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["camera.media.v1"] = CAMERA_MEDIA_CONTRACT_VERSION


class CameraSource(ClosedMessage):
    message_type: Literal["camera.source"] = "camera.source"
    audience: Literal["core-sidecar"] = "core-sidecar"
    camera_id: str = Field(min_length=1, max_length=300, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    source_url: SecretStr
    source_protocol: Literal["rtsp", "rtsps"]
    preferred_transport: Literal["tcp", "udp", "auto"] = "auto"
    connect_timeout_seconds: int = Field(default=10, ge=1, le=60)

    @model_validator(mode="after")
    def validate_source(self) -> CameraSource:
        source = validate_source_url(self.source_url.get_secret_value())
        if not source.lower().startswith(f"{self.source_protocol}://"):
            raise ValueError("source protocol does not match source_url")
        return self


class CameraOffer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["offer"] = "offer"
    sdp: str = Field(min_length=1, max_length=MAX_SDP_BYTES)
    include_audio: bool = False


class OpenCameraSession(ClosedMessage):
    message_type: Literal["camera.sidecar.session.open"] = "camera.sidecar.session.open"
    audience: Literal["core-sidecar"] = "core-sidecar"
    source: CameraSource
    offer: CameraOffer
    idle_timeout_seconds: int = Field(default=60, ge=10, le=900)


@router.post("/sessions", status_code=201)
async def open_camera_session(request: OpenCameraSession) -> dict[str, object]:
    try:
        active, answer_sdp = await media_session_broker.open(
            source_url=request.source.source_url.get_secret_value(),
            offer_sdp=request.offer.sdp,
            idle_timeout_seconds=request.idle_timeout_seconds,
            preferred_transport=request.source.preferred_transport,
            connect_timeout_seconds=request.source.connect_timeout_seconds,
            include_audio=request.offer.include_audio,
        )
    except CameraMediaCapacityError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "contract_version": CAMERA_MEDIA_CONTRACT_VERSION,
                "message_type": "camera.error",
                "audience": "core-sidecar",
                "code": "CAMERA_CAPACITY_REACHED",
                "message": "Camera media capacity has been reached.",
                "retryable": True,
                "retry_after_seconds": 5,
            },
        ) from exc
    except CameraSourceUnavailableError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "contract_version": CAMERA_MEDIA_CONTRACT_VERSION,
                "message_type": "camera.error",
                "audience": "core-sidecar",
                "code": "CAMERA_SOURCE_UNAVAILABLE",
                "message": "The camera source is unavailable.",
                "retryable": True,
                "retry_after_seconds": 5,
            },
        ) from exc
    except (Go2RtcError, httpx.HTTPError, ValueError) as exc:
        logger.warning("camera media signaling failed: %s", exc)
        raise HTTPException(status_code=502, detail="camera WebRTC signaling failed") from exc
    return {
        "contract_version": CAMERA_MEDIA_CONTRACT_VERSION,
        "message_type": "camera.session.opened",
        "audience": "core-sidecar",
        "session_id": active.session_id,
        "type": "answer",
        "sdp": answer_sdp,
        "expires_at": active.expires_at.isoformat().replace("+00:00", "Z"),
    }


@router.delete("/sessions/{session_id}", status_code=204)
async def close_camera_session(session_id: str) -> Response:
    await media_session_broker.close(session_id)
    return Response(status_code=204)


@router.put("/sessions/{session_id}/keepalive")
async def keep_camera_session_alive(session_id: str) -> dict[str, object]:
    active = await media_session_broker.touch(session_id)
    if active is None:
        raise HTTPException(status_code=404, detail="Camera media session was not found.")
    return {
        "contract_version": CAMERA_MEDIA_CONTRACT_VERSION,
        "message_type": "camera.session.refreshed",
        "audience": "core-sidecar",
        "session_id": active.session_id,
        "expires_at": active.expires_at.isoformat().replace("+00:00", "Z"),
    }


@router.get("/status")
async def camera_media_status() -> dict[str, object]:
    ready = True
    degraded_reason = None
    try:
        await media_session_broker.client.health()
    except (Go2RtcError, httpx.HTTPError, ValueError, AttributeError):
        ready = False
        degraded_reason = "media_control_plane_unavailable"
    return {
        "contract_version": CAMERA_MEDIA_CONTRACT_VERSION,
        "message_type": "camera.sidecar.status",
        "audience": "core-sidecar",
        "ready": ready,
        "active_sessions": media_session_broker.active_count,
        "session_capacity": media_session_broker.capacity,
        "degraded_reason": degraded_reason,
        "supported_source_protocols": ["rtsp", "rtsps"],
        "supported_transports": ["webrtc"],
    }
