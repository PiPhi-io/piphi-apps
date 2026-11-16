from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..bridge import BridgeUnavailableError, bridge_supervisor
from ..schemas import WyzeBridgeConfig
from .auth import require_wyze_bridge_authorization

router = APIRouter(
    prefix="/v1/wyze-bridge",
    tags=["wyze-bridge"],
    dependencies=[Depends(require_wyze_bridge_authorization)],
)


@router.put("/config")
async def configure(payload: WyzeBridgeConfig) -> dict[str, object]:
    try:
        await bridge_supervisor.configure(payload)
    except BridgeUnavailableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "service": bridge_supervisor.status()}


@router.delete("/config")
async def deconfigure() -> dict[str, object]:
    await bridge_supervisor.stop()
    return {"ok": True, "service": bridge_supervisor.status()}


@router.get("/status")
async def status() -> dict[str, object]:
    return bridge_supervisor.status()


@router.get("/cameras")
async def cameras() -> dict[str, object]:
    try:
        return {"cameras": await bridge_supervisor.cameras()}
    except BridgeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
