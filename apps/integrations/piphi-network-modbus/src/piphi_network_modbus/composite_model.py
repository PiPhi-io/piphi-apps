from __future__ import annotations

from typing import Any

from .contract import COMMANDS
from .schemas import CompositeProfile


WIDGETS = {
    "light": ["light", "tile", "button"],
    "fan": ["fan", "tile", "stat"],
    "cover": ["cover", "tile", "button"],
    "climate": ["thermostat", "tile", "stat"],
}


def _command_definition(command_id: str) -> dict[str, Any]:
    definition = COMMANDS[command_id]
    command: dict[str, Any] = {
        "id": command_id,
        "label": command_id.replace("_", " ").title(),
        "kind": "action",
    }
    if definition.get("args_schema"):
        command["args_schema"] = definition["args_schema"]
    return command


def normalize_composites(
    composites: list[CompositeProfile],
    points: list[dict[str, Any]],
    *,
    config_id: str,
) -> list[dict[str, Any]]:
    point_by_id = {str(point["point_id"]): point for point in points}
    models: list[dict[str, Any]] = []
    for composite in composites:
        sources = {
            role: point_by_id[point_id]
            for role, point_id in composite.state_points.items()
        }
        qualities = [source["state"].get("quality") for source in sources.values()]
        timestamps = [
            str(source["state"]["updated_at"])
            for source in sources.values()
            if source["state"].get("updated_at")
        ]
        command_ids = ["refresh", *composite.commands]
        device_id = f"{config_id}:{composite.id}"
        models.append(
            {
                "id": device_id,
                "device_id": device_id,
                "config_id": config_id,
                "composite_id": composite.id,
                "name": composite.name,
                "device_class": composite.entity_type,
                "entity_type": composite.entity_type,
                "capabilities": [
                    "connected",
                    *composite.state_points,
                    *command_ids,
                ],
                "available_commands": [
                    _command_definition(command_id) for command_id in command_ids
                ],
                "state": {
                    "connected": bool(qualities)
                    and all(quality == "good" for quality in qualities),
                    "quality": (
                        "good"
                        if qualities and all(quality == "good" for quality in qualities)
                        else "stale"
                        if any(quality in {"good", "stale"} for quality in qualities)
                        else "unavailable"
                    ),
                    "updated_at": max(timestamps) if timestamps else None,
                    **{
                        role: source["state"].get("point_value")
                        for role, source in sources.items()
                    },
                },
                "metadata": {
                    "profile_composite": True,
                    "state_points": composite.state_points,
                    "command_points": {
                        command_id: binding.point_id
                        for command_id, binding in composite.commands.items()
                    },
                },
                "dashboard": {
                    "allowed_widgets": WIDGETS[composite.entity_type],
                    "default_widget": WIDGETS[composite.entity_type][0],
                },
            }
        )
    return models
