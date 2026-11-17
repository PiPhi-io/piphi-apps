from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python import (
    RuntimeConfig,
    RuntimeConfigSnapshot,
    build_config_apply_response,
    build_config_remove_response,
    validate_typed_configs,
)
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from ..routeros import RouterOSError
from ..schemas import DeviceConfig
from ..state import (
    apply_config,
    config_sync,
    registry,
    remove_config,
    runtime,
)

router = APIRouter(tags=["config"])


async def _apply_synced_config(config: RuntimeConfig) -> None:
    await apply_config(DeviceConfig.model_validate(config.model_dump()))


@router.post("/config")
async def configure(payload: DeviceConfig, request: Request):
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    try:
        await apply_config(payload)
    except RouterOSError as exc:
        status = {
            "authentication_failed": 401,
            "permission_denied": 403,
            "rate_limited": 429,
        }.get(exc.reason, 503 if exc.retryable else 422)
        raise HTTPException(status_code=status, detail=exc.reason) from exc
    except ValueError as exc:
        if "already configured" in str(exc) or "different RouterOS appliance" in str(
            exc
        ):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={"host": payload.host, "alias": payload.alias},
    )


@router.post("/config/sync")
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request):
    runtime.auth.sync_from_headers(
        request.headers, payload_container_id=snapshot.container_id
    )
    typed_configs = validate_typed_configs(snapshot.configs, DeviceConfig)
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=_apply_synced_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@router.post("/deconfigure")
async def deconfigure(payload: dict[str, Any]):
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
async def deconfigure_by_path(config_id: str):
    removed = await remove_config(config_id)
    return build_config_remove_response(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )
