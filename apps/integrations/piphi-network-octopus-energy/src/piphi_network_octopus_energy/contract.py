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
    "current_rate": {"kind": "sensor", "value_kind": "numeric", "unit": "p/kWh"},
    "next_rate": {"kind": "sensor", "value_kind": "numeric", "unit": "p/kWh"},
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
        "title": "Piphi Network Octopus Energy Setup",
        "type": "object",
        "required": ["product_code", "tariff_code"],
        "properties": {
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "product_code": {"type": "string", "title": "Electricity product code"},
            "tariff_code": {"type": "string", "title": "Electricity tariff code"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 15
            }
        }
    },
    "uiSchema": {
        "alias": {
            "placeholder": "Home electricity"
        },
        "product_code": {"placeholder": "AGILE-FLEX-22-11-25"},
        "tariff_code": {"placeholder": "E-1R-AGILE-FLEX-22-11-25-A"},
        "poll_interval_seconds": {
            "placeholder": "60"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "energy_account",
    "capabilities": [
        "connected",
        "current_rate",
        "next_rate",
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
