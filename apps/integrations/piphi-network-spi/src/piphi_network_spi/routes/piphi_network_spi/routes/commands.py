from __future__ import annotations

from fastapi import APIRouter, HTTPException
from piphi_runtime_kit_python import IntegrationCommandRequest

from ..state import (
    SPISensorRuntimeConfig,
    append_runtime_event,
    config_to_sensor_config,
    primary_config,
    registry,
    read_state,
)

router = APIRouter(tags=["commands"])


@router.post("/command")
async def command(payload: IntegrationCommandRequest) -> dict[str, object]:
    if payload.command != "refresh":
        raise HTTPException(status_code=400, detail=f"Unsupported command: {payload.command}")
    config_id = (payload.entity_id or payload.device_id or registry.ids()[0]) if registry.ids() else primary_config().id
    entry = registry.get(config_id) or registry.primary_entry()
    config = SPISensorRuntimeConfig.model_validate(entry["config"]) if entry else primary_config()
    try:
        state_payload = read_state(config_to_sensor_config(config))
    except Exception as exc:
        if entry:
            registry.update_state(
                config.id,
                {"connected": False, "error": str(exc)},
                device_id=(entry or {}).get("device_id"),
            )
            append_runtime_event("spi.sensor.refresh_failed", entry, {"command": payload.command, "error": str(exc)})
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    registry.update_state(config.id, state_payload, device_id=(entry or {}).get("device_id"))
    if entry:
        append_runtime_event("spi.sensor.refreshed", entry, {"command": payload.command})
    return {"ok": True, "state": state_payload}
