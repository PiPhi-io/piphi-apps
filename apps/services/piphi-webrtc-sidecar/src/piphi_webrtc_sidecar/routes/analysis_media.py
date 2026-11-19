from __future__ import annotations

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ..analysis_media import (
    AnalysisMediaCapacityError,
    AnalysisMediaCaptureError,
    AnalysisMediaCleanupError,
    AnalysisMediaSizeError,
    AnalysisMediaTypeError,
    analysis_media_broker,
)
from ..authorization import authorize_sidecar_request
from ..contract import ANALYSIS_MEDIA_CONTRACT_VERSION
from ..go2rtc import Go2RtcError
from .media_sidecar import CameraSource

logger = logging.getLogger(__name__)


def require_analysis_media_authorization(request: Request) -> None:
    authorize_sidecar_request(request)


router = APIRouter(
    prefix="/v1/analysis-media",
    tags=["analysis-media"],
    dependencies=[Depends(require_analysis_media_authorization)],
)


class IssueAnalysisMedia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["camera.analysis-media.v1"] = ANALYSIS_MEDIA_CONTRACT_VERSION
    message_type: Literal["camera.analysis-media.issue"] = "camera.analysis-media.issue"
    audience: Literal["core-sidecar"] = "core-sidecar"
    source: CameraSource
    ttl_seconds: int = Field(default=30, ge=1, le=60)


@router.post("", status_code=201)
async def issue_analysis_media(request: IssueAnalysisMedia) -> dict[str, object]:
    try:
        issued = await analysis_media_broker.issue(
            source_url=request.source.source_url.get_secret_value(),
            ttl_seconds=request.ttl_seconds,
        )
    except AnalysisMediaCapacityError as exc:
        raise HTTPException(
            status_code=429, detail="Analysis media capacity has been reached."
        ) from exc
    except AnalysisMediaSizeError as exc:
        raise HTTPException(status_code=413, detail="The captured image is too large.") from exc
    except AnalysisMediaTypeError as exc:
        raise HTTPException(status_code=415, detail="The captured image is not supported.") from exc
    except AnalysisMediaCleanupError as exc:
        logger.warning("analysis media cleanup failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Analysis media capture failed.") from None
    except (AnalysisMediaCaptureError, Go2RtcError, httpx.HTTPError, ValueError) as exc:
        logger.warning("analysis media capture failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Analysis media capture failed.") from None
    return {
        "contract_version": ANALYSIS_MEDIA_CONTRACT_VERSION,
        "message_type": "camera.analysis-media.issued",
        "audience": "core-sidecar",
        "media_ref": issued.media_ref,
        "expires_at": issued.expires_at.isoformat().replace("+00:00", "Z"),
    }


@router.get("/{media_ref}")
async def consume_analysis_media(media_ref: str) -> Response:
    media = await analysis_media_broker.consume(media_ref)
    if media is None:
        raise HTTPException(status_code=404, detail="Analysis media was not found.")
    return Response(content=media.content, media_type=media.content_type)


@router.delete("/{media_ref}", status_code=204)
async def revoke_analysis_media(media_ref: str) -> Response:
    await analysis_media_broker.revoke(media_ref)
    return Response(status_code=204)
