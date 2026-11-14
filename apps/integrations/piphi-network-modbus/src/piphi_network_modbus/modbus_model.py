from __future__ import annotations

from typing import Any


def normalize_snapshot(snapshot: dict[str, Any], *, config_id: str) -> list[dict[str, Any]]:
    points = snapshot.get("points")
    if not isinstance(points, list):
        raise ValueError("snapshot_points_missing")
    models: list[dict[str, Any]] = []
    for raw in points:
        if not isinstance(raw, dict):
            continue
        point_id = str(raw.get("id") or "").strip()
        if not point_id:
            continue
        writable = bool(raw.get("writable"))
        is_bool = raw.get("data_type") == "bool"
        device_id = f"{config_id}:{point_id}"
        commands = [{"id": "refresh", "label": "Refresh", "kind": "action"}]
        if writable:
            commands.append({"id": "set_value", "label": "Set value", "kind": "action"})
        capabilities = ["connected", "point_value", "refresh"]
        if writable:
            capabilities.append("set_value")
        models.append(
            {
                "id": device_id,
                "device_id": device_id,
                "config_id": config_id,
                "point_id": point_id,
                "name": str(raw.get("name") or point_id),
                "entity_type": "switch" if is_bool and writable else "binary_sensor" if is_bool else "sensor",
                "capabilities": capabilities,
                "available_commands": commands,
                "state": {
                    "connected": raw.get("quality") == "good",
                    "point_value": raw.get("value"),
                    "quality": raw.get("quality", "unknown"),
                    "updated_at": raw.get("updated_at"),
                    "unit": raw.get("unit"),
                },
                "metadata": {
                    key: raw.get(key)
                    for key in ("area", "data_type", "byte_order", "unit", "minimum", "maximum", "writable")
                },
                "dashboard": {
                    "allowed_widgets": ["tile", "stat", "button"],
                    "default_widget": "tile",
                },
            }
        )
    return models


def entity_response(model: dict[str, Any]) -> dict[str, Any]:
    return {
        key: model[key]
        for key in (
            "id",
            "device_id",
            "config_id",
            "name",
            "entity_type",
            "capabilities",
            "available_commands",
            "state",
            "metadata",
            "dashboard",
        )
    }
