from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..state import get_controller

router = APIRouter(prefix="/v1/modbus", tags=["parent-sidecar"])


@router.get("/snapshot")
async def snapshot(config_id: str | None = None) -> dict[str, Any]:
    return get_controller(config_id).snapshot()


@router.get("/events")
async def events(
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    config_id: str | None = None,
) -> dict[str, Any]:
    return get_controller(config_id).events.read(after=after, limit=limit).__dict__


@router.post("/refresh")
async def refresh(payload: dict[str, Any]) -> dict[str, Any]:
    controller = get_controller(str(payload.get("config_id") or "") or None)
    point_id = str(payload.get("point_id") or "").strip()
    try:
        if point_id:
            await controller.refresh_point(point_id)
        else:
            await controller.refresh_all()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return controller.snapshot()


@router.post("/write")
async def write(payload: dict[str, Any]) -> dict[str, Any]:
    controller = get_controller(str(payload.get("config_id") or "") or None)
    forbidden = {"address", "unit_id", "function", "raw", "pdu"} & payload.keys()
    if forbidden:
        raise HTTPException(status_code=400, detail="transport_overrides_are_not_allowed")
    point_id = str(payload.get("point_id") or "").strip()
    if not point_id:
        raise HTTPException(status_code=400, detail="point_id_required")
    try:
        result = await controller.write_point(point_id, payload.get("value"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "point_id": point_id, **result}
