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
    "connected": {"kind": "sensor", "unit": "bool"},
    "temperature_c": {"kind": "sensor", "unit": "°C"},
    "humidity_percent": {"kind": "sensor", "unit": "%"},
    "battery_percent": {"kind": "sensor", "unit": "%"},
    "rssi_dbm": {"kind": "sensor", "unit": "dBm"},
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Run a bounded Bluetooth scan for this sensor.",
        "timeout_ms": 10000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "BTHome Sensor Setup",
        "type": "object",
        "required": [
            "host"
        ],
        "properties": {
            "host": {
                "type": "string",
                "title": "BLE address",
                "description": "MAC address of an unencrypted BTHome v2 sensor, as seen by this host"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Scan interval (seconds)",
                "minimum": 30,
                "maximum": 3600,
                "default": 60
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "AA:BB:CC:DD:EE:FF"
        },
        "alias": {
            "placeholder": "Living room sensor"
        },
        "poll_interval_seconds": {
            "placeholder": "60"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "configured-bthome-sensor",
    "name": "BTHome sensor",
    "device_id": "configured-bthome-sensor",
    "entity_type": "sensor",
    "capabilities": [
        "connected",
        "temperature_c",
        "humidity_percent",
        "battery_percent",
        "rssi_dbm",
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
