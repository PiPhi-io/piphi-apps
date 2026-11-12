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
    "refresh": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Ble Gateway Sidecar Setup",
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
            "service_name": {
                "type": "string",
                "title": "Service Name"
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Office Device"
        },
        "service_name": {
            "placeholder": "local-helper"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "ble-gateway-service",
    "name": "BLE Gateway Service",
    "device_id": "ble-gateway-service",
    "entity_type": "service",
    "capabilities": [
        "connected",
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
