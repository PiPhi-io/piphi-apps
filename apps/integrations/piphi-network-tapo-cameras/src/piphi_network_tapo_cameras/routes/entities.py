from typing import Any

from fastapi import APIRouter

from ..contract import ENTITY_TEMPLATE
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    result = []
    for entry in registry.entries.values():
        entity_capabilities = [item for item in ENTITY_TEMPLATE["capabilities"] if item not in {"privacy_mode", "camera_enabled"} or entry.get("privacy_mode") is not None]
        result.append({"id": entry["device_id"], "name": entry.get("alias") or entry.get("name") or "Tapo camera", "config_id": entry["config_id"], "device_id": entry["device_id"], **ENTITY_TEMPLATE, "capabilities": entity_capabilities, "metadata": {"model": entry.get("model"), "hardware": entry.get("hardware"), "firmware": entry.get("firmware"), "device_type": entry.get("device_type"), "availability": entry.get("availability")}})
    return {"entities": result, "capabilities": capabilities, "commands": commands}
