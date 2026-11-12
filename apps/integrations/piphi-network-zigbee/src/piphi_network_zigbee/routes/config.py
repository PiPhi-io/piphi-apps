from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
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
    config_sync,
    registry,
    remove_config,
    runtime,
)

router = APIRouter(tags=["config"])


def _snapshot_configs_as_payloads(snapshot: RuntimeConfigSnapshot) -> list[dict[str, Any]]:
    return [
        config.model_dump() if hasattr(config, "model_dump") else dict(config)
        for config in snapshot.configs
    ]


def _normalize_synced_config_identity(config: DeviceConfig) -> DeviceConfig:
    entry_id = str(config.config_id or config.id).strip()
    if not entry_id or config.id == entry_id:
        return config
    return config.model_copy(update={"id": entry_id})


@router.post("/config")
async def configure(payload: DeviceConfig, request: Request):
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={
            "friendly_name": payload.friendly_name,
            "ieee_address": payload.ieee_address,
            "alias": payload.alias,
        },
    )


@router.post("/config/sync")
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request):
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    typed_configs = [
        _normalize_synced_config_identity(config)
        for config in validate_typed_configs(_snapshot_configs_as_payloads(snapshot), DeviceConfig)
    ]
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_config,
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
