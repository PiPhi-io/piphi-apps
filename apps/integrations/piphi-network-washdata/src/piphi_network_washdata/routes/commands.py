from typing import Any

from fastapi import APIRouter, HTTPException, Request
from piphi_runtime_kit_python.fastapi import dispatch_automation_action_from_fastapi

from ..state import automations

router = APIRouter(tags=["commands"])


@router.post("/command")
async def command(payload: dict[str, Any], request: Request):
    if str(payload.get("command") or "") != "refresh":
        raise HTTPException(
            status_code=400, detail={"error": "unsupported_command", "monitoring_only": True}
        )
    raw_target = payload.get("target")
    target: dict[str, Any] = raw_target if isinstance(raw_target, dict) else {}
    result = await dispatch_automation_action_from_fastapi(
        automations,
        request,
        {
            **payload,
            "command": "refresh",
            "args": {},
            "config_id": payload.get("config_id") or target.get("config_id"),
            "target": target,
        },
    )
    response = result.model_dump(mode="json")
    if result.ok:
        response.update(result.result)
    return response
