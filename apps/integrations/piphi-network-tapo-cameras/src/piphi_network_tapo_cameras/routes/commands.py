from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python.fastapi import dispatch_automation_action_from_fastapi

from ..state import automations

router = APIRouter(tags=["commands"])


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    command_name = str(payload.get("command") or "").strip()
    if command_name != "refresh":
        raise HTTPException(status_code=400, detail={"error": "unsupported_command"})
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    result = await dispatch_automation_action_from_fastapi(automations, request, {**payload, "command": "refresh", "args": {}, "config_id": payload.get("config_id") or target.get("config_id"), "device_id": payload.get("device_id") or target.get("device_id"), "target": target})
    response = result.model_dump(mode="json")
    if result.ok:
        response.update(result.result)
    return response
