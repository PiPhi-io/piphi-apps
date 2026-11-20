from typing import Any

from fastapi import APIRouter

from ..contract import ENTITY_TEMPLATE
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    result = []
    for entry in registry.entries.values():
        for point in entry.get("climate_points", []):
            available_commands = [
                {"id": "refresh", "label": "Refresh", "kind": "action"}
            ]
            if entry.get("enable_climate_control") and point.get("target_settable"):
                available_commands.append(
                    {
                        "id": "set_target_temperature",
                        "label": "Set target temperature",
                        "kind": "action",
                    }
                )
            result.append(
                {
                    "id": point["device_id"],
                    "name": point["name"],
                    "config_id": entry["config_id"],
                    "device_id": point["device_id"],
                    **ENTITY_TEMPLATE,
                    "available_commands": available_commands,
                    "metadata": {
                        "model": point.get("model"),
                        "availability": entry.get("availability"),
                        "target_temperature_min_c": point.get(
                            "target_temperature_min_c"
                        ),
                        "target_temperature_max_c": point.get(
                            "target_temperature_max_c"
                        ),
                        "target_temperature_step_c": point.get(
                            "target_temperature_step_c"
                        ),
                    },
                }
            )
    return {"entities": result, "capabilities": capabilities, "commands": commands}
