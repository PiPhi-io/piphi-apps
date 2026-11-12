from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from piphi_runtime_kit_python import (
    RuntimeConfig,
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


async def apply_synced_config(value: RuntimeConfig) -> None:
    typed = (
        value
        if isinstance(value, DeviceConfig)
        else DeviceConfig.model_validate(value.model_dump())
    )
    await apply_config(typed)


@router.post("/config")
async def configure(payload: DeviceConfig, request: Request) -> Any:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={
            "host": payload.host,
            "alias": payload.alias,
            "api": "pfrest-v2",
            "read_only": True,
            "simulation_mode": payload.simulation_mode,
        },
    )


@router.post("/config/sync")
async def sync_config(snapshot: RuntimeConfigSnapshot, request: Request) -> Any:
    runtime.auth.sync_from_headers(
        request.headers, payload_container_id=snapshot.container_id
    )
    # RuntimeConfigSnapshot intentionally parses entries as the SDK base model.
    # Rehydrate their complete payloads before applying the integration schema.
    config_payloads: list[Mapping[str, Any]] = [
        value.model_dump() for value in snapshot.configs
    ]
    typed_configs: list[DeviceConfig] = validate_typed_configs(
        config_payloads,
        DeviceConfig,
    )
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_synced_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


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
