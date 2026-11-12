from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from piphi_runtime_kit_python import (
    RuntimeConfigApplyResponse,
    RuntimeConfigRemoveResponse,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
    build_config_apply_response,
    build_config_remove_response,
)
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..state import (
    SPISensorRuntimeConfig,
    apply_config,
    config_sync,
    primary_config,
    registry,
    remove_config,
    runtime,
    typed_snapshot_configs,
)

router = APIRouter(tags=["config"])


@router.post("/config", response_model=RuntimeConfigApplyResponse)
async def configure(payload: SPISensorRuntimeConfig, request: Request) -> RuntimeConfigApplyResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={"adapter": payload.adapter, "bus": payload.bus, "sensor_model": payload.sensor_model},
    )


@router.get("/config")
async def get_config() -> dict[str, Any]:
    return {"configs": [entry["config"] for entry in registry.entries.values()]}


@router.post("/configs/sync", response_model=RuntimeConfigSyncResponse)
@router.post("/config/sync", response_model=RuntimeConfigSyncResponse)
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request) -> RuntimeConfigSyncResponse:
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    try:
        typed_configs = typed_snapshot_configs(snapshot)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@router.post("/deconfigure/{config_id}", response_model=RuntimeConfigRemoveResponse)
async def deconfigure_config(config_id: str) -> RuntimeConfigRemoveResponse:
    removed = await remove_config(config_id)
    return build_config_remove_response(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )


@router.post("/deconfigure", response_model=RuntimeConfigRemoveResponse)
async def deconfigure(payload: dict[str, Any] | None = None) -> RuntimeConfigRemoveResponse:
    config_id = str((payload or {}).get("config_id") or (payload or {}).get("id") or primary_config().id)
    removed = await remove_config(config_id)
    return build_config_remove_response(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )
