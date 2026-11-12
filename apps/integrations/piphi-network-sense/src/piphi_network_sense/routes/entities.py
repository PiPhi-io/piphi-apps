from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..contract import FALLBACK_ENTITY
from ..state import capabilities, commands, registry

router = APIRouter(tags=["entities"])


@router.get("/entities")
async def entities() -> dict[str, Any]:
    entries = list(registry.entries.values())
    runtime_entities: list[dict[str, Any]] = []
    for entry in entries:
        config_id = str(entry["config_id"])
        snapshot_record = registry.state_snapshots.get(config_id, {})
        snapshot = snapshot_record.get("state", snapshot_record)
        runtime_entities.append(
            {
                **FALLBACK_ENTITY,
                "id": str(entry["device_id"]),
                "name": entry.get("alias") or "Sense Energy Monitor",
                "config_id": config_id,
                "device_id": str(entry["device_id"]),
            }
        )
        for device in snapshot.get("devices", []):
            runtime_entities.append(
                {
                    "id": f"sense-device-{device['device_id']}",
                    "name": device["name"],
                    "config_id": config_id,
                    "device_id": str(device["device_id"]),
                    "entity_type": "energy_device",
                    "capabilities": [
                        "device_power_w",
                        "device_on",
                        "device_daily_energy_kwh",
                    ],
                    "available_commands": [],
                    "metadata": {
                        "sense_device_type": device.get("device_type"),
                        "sense_first_usage": device.get("first_usage"),
                        "sense_timeline_enabled": device.get("timeline_enabled"),
                    },
                    "dashboard": {
                        "allowed_widgets": ["stat", "gauge", "line-chart"],
                        "default_widget": "stat",
                    },
                }
            )
    if not runtime_entities:
        runtime_entities = [FALLBACK_ENTITY]
    return {"entities": runtime_entities, "capabilities": capabilities, "commands": commands}
