from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..remote_v2_pairing import (
    InvalidConfigIdError,
    PairingAlreadyActiveError,
    PairingSessionNotFoundError,
)
from ..schemas import normalize_host
from ..state import credential_store, pairing_manager, registry

router = APIRouter(prefix="/pairing", tags=["pairing"])


class PairingStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_id: str = Field(min_length=1, max_length=128)
    host: str = Field(min_length=1, max_length=253)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        return normalize_host(value)


class PairingFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: str = Field(min_length=6, max_length=6)


@router.post("/start")
async def start_pairing(payload: PairingStartRequest):
    try:
        session = await pairing_manager.start_pairing(
            config_id=payload.config_id,
            host=payload.host,
        )
    except InvalidConfigIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PairingAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Android TV pairing timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to start Android TV pairing") from exc
    return {
        "session_id": session.session_id,
        "config_id": session.config_id,
        "device_name": session.device_name,
        "status": "pin_required",
    }


@router.post("/{session_id}/finish")
async def finish_pairing(session_id: str, payload: PairingFinishRequest):
    try:
        await pairing_manager.finish_pairing(session_id, payload.pin)
    except PairingSessionNotFoundError as exc:
        raise HTTPException(status_code=410, detail="Pairing session expired or was used") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Android TV pairing timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Android TV rejected the pairing PIN") from exc
    return {"status": "paired"}


@router.delete("/{session_id}", status_code=204)
async def cancel_pairing(session_id: str) -> Response:
    try:
        await pairing_manager.cancel_pairing(session_id)
    except PairingSessionNotFoundError as exc:
        raise HTTPException(status_code=410, detail="Pairing session expired or was used") from exc
    return Response(status_code=204)


@router.delete("/credentials/{config_id}")
async def forget_credentials(config_id: str):
    if registry.get(config_id) is not None:
        raise HTTPException(
            status_code=409,
            detail="Deconfigure the Android TV before forgetting its credentials",
        )
    try:
        if not credential_store.has_credentials(config_id):
            raise HTTPException(status_code=404, detail="No stored credentials")
        credential_store.remove_credentials(config_id)
    except InvalidConfigIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "forgotten", "config_id": config_id}
