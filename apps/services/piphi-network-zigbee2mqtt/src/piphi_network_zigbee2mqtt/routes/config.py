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


@router.post("/config")
async def configure(payload: DeviceConfig, request: Request):
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={
            "host": payload.host,
            "alias": payload.alias,
            "serial_port": payload.serial_port,
            "adapter": payload.adapter,
        },
    )


@router.post("/config/sync")
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request):
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    typed_configs = validate_typed_configs(_runtime_config_payloads(snapshot.configs), DeviceConfig)
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


def _runtime_config_payloads(configs: list[Any]) -> list[dict[str, Any] | Any]:
    payloads: list[dict[str, Any] | Any] = []
    for config in configs:
        if isinstance(config, dict):
            payloads.append(config)
            continue
        if hasattr(config, "model_dump"):
            payloads.append(config.model_dump(mode="python"))
            continue
        payloads.append(config)
    return payloads


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
