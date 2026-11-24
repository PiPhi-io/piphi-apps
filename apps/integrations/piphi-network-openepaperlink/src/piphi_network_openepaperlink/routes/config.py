from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    RuntimeConfigSnapshot,
    build_config_apply_response,
    build_config_remove_response,
    validate_typed_configs,
)
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..schemas import DeviceConfig
from ..state import (
    apply_config,
    apply_config_snapshot,
    registry,
    remove_config,
    runtime,
)

router = APIRouter(tags=["config"])


@router.post("/config")
async def configure(payload: DeviceConfig, request: Request) -> Any:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    try:
        await apply_config(payload)
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={"alias": payload.alias},
    )


@router.post("/config/sync")
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request) -> Any:
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    typed_configs = validate_typed_configs(snapshot.configs, DeviceConfig)
    try:
        return await apply_config_snapshot(snapshot.model_copy(update={"configs": typed_configs}))
    except ConnectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/deconfigure")
async def deconfigure(payload: dict[str, Any]) -> Any:
    config_id = payload.get("config_id") or payload.get("configId")
    if not config_id:
        return {"ok": False, "reason": "missing config_id"}
    removed = await remove_config(str(config_id))
    return build_config_remove_response(
        config_id=str(config_id),
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )


@router.post("/deconfigure/{config_id}")
async def deconfigure_by_path(config_id: str) -> Any:
    removed = await remove_config(config_id)
    return build_config_remove_response(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )
