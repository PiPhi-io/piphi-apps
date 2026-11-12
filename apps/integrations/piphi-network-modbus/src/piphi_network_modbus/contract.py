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
    "holding_register_value": {"kind": "sensor", "value_kind": "numeric"},
    "refresh": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 12000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Modbus TCP register",
        "type": "object",
        "required": ["host", "register_address"],
        "properties": {
            "host": {
                "type": "string",
                "title": "Host"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "register_address": {"type": "integer", "title": "Zero-based holding register address", "minimum": 0, "maximum": 65535},
            "unit_id": {"type": "integer", "title": "Modbus unit ID", "minimum": 1, "maximum": 247},
            "poll_interval_seconds": {"type": "integer", "title": "Poll interval (seconds)", "minimum": 60}
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Meter register"
        },
        "register_address": {"placeholder": "0"},
        "unit_id": {"placeholder": "1"},
        "poll_interval_seconds": {"placeholder": "300"}
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "modbus_device",
    "capabilities": [
        "connected",
        "holding_register_value",
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
