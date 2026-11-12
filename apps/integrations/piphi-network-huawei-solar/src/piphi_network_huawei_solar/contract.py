from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "discover": "/discover",
    "entities": "/entities",
    "state": "/state",
    "config": "/config",
    "config_sync": "/config/sync",
    "deconfigure": "/deconfigure",
    "ui_config": "/ui-config",
    "events": "/events",
    "command": "/command",
}

REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {
        "kind": "sensor",
        "unit": "bool"
    },
    "active_power_w": {"kind": "sensor", "unit": "W", "value_kind": "numeric"},
    "daily_yield_kwh": {"kind": "sensor", "unit": "kWh", "value_kind": "numeric"},
    "refresh": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 15000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Huawei SUN2000 Modbus TCP",
        "type": "object",
        "required": [
            "host"
        ],
        "properties": {
            "host": {
                "type": "string",
                "title": "Host"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "unit_id": {"type": "integer", "title": "Modbus unit ID", "minimum": 0, "maximum": 247},
            "poll_interval_seconds": {"type": "integer", "title": "Poll interval (seconds)", "minimum": 60}
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Solar inverter"
        },
        "unit_id": {"placeholder": "1"},
        "poll_interval_seconds": {"placeholder": "300"}
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "solar_system",
    "capabilities": [
        "connected",
        "active_power_w",
        "daily_yield_kwh",
        "refresh"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        }
    ],
    "dashboard": {
        "allowed_widgets": [
            "tile",
            "stat",
            "button"
        ],
        "default_widget": "tile"
    }
}
