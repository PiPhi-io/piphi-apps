from fastapi import APIRouter

from ..contract import ENTITY_TEMPLATE
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities():
    values = [
        {
            "id": entry["device_id"],
            "name": entry["alias"],
            "config_id": entry["config_id"],
            "device_id": entry["device_id"],
            **ENTITY_TEMPLATE,
            "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
            "metadata": {"binding_key": entry["binding_key"]},
        }
        for entry in registry.entries.values()
    ]
    return {"entities": values, "capabilities": capabilities, "commands": commands}
