from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..state import MANIFEST, UI_CONFIG_SCHEMA, read_current_state

router = APIRouter(tags=["runtime"])


@router.get("/manifest.json")
async def manifest() -> dict[str, Any]:
    return MANIFEST


@router.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return UI_CONFIG_SCHEMA


@router.get("/state")
async def state() -> dict[str, Any]:
    return read_current_state()
