from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..state import MANIFEST, UI_CONFIG_SCHEMA, read_current_state, starter

router = APIRouter(tags=["runtime"])


@router.get("/manifest.json")
async def manifest() -> dict[str, Any]:
    return MANIFEST


@router.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return UI_CONFIG_SCHEMA


@router.get("/state")
async def state(
    refresh: bool = Query(default=False),
    refresh_request_id: str | None = Query(default=None),
) -> dict[str, Any]:
    if not refresh:
        return read_current_state()
    try:
        return await starter.state.response(
            refresh=True,
            refresh_request_id=refresh_request_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
