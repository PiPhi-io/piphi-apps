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
    "receiver_healthy": {"kind": "sensor", "unit": "bool"},
    "observation_fresh": {"kind": "sensor", "unit": "bool"},
    "sensor_available": {"kind": "sensor", "unit": "bool"},
    "measurement_age_seconds": {"kind": "sensor", "unit": "s"},
    "temperature_c": {"kind": "sensor", "unit": "°C"},
    "humidity_percent": {"kind": "sensor", "unit": "%"},
    "battery_percent": {"kind": "sensor", "unit": "%"},
    "rssi_dbm": {"kind": "sensor", "unit": "dBm"},
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Poll the managed BLE gateway for this sensor.",
        "timeout_ms": 10000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "BTHome Sensor Setup",
        "type": "object",
        "required": ["gateway_url", "gateway_token", "device_handle"],
        "properties": {
            "gateway_url": {
                "type": "string",
                "title": "BLE gateway URL",
                "description": "HTTPS URL for the managed PiPhi BLE gateway v1 API"
            },
            "gateway_token": {
                "type": "string",
                "format": "password",
                "title": "Gateway token",
                "description": "Bearer token; never returned in state or diagnostics"
            },
            "bind_key": {
                "type": "string",
                "format": "password",
                "title": "BTHome bind key (optional)",
                "description": "16-byte hexadecimal key; sent only to the gateway's scoped in-memory consumer"
            },
            "device_handle": {
                "type": "string",
                "title": "Approved device handle",
                "description": "Opaque handle selected with explicit consent in the BLE gateway"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Scan interval (seconds)",
                "minimum": 2,
                "maximum": 300,
                "default": 10
            },
            "stale_after_seconds": {
                "type": "integer",
                "title": "Observation stale after (seconds)",
                "minimum": 30,
                "maximum": 86400,
                "default": 180
            }
        }
    },
    "uiSchema": {
        "gateway_url": {
            "placeholder": "https://ble-gateway.local:4210"
        },
        "device_handle": {
            "placeholder": "ble_c7f2a1b9000000000000000000000000"
        },
        "bind_key": {
            "ui:widget": "password",
            "placeholder": "32 hexadecimal characters"
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
        "receiver_healthy",
        "observation_fresh",
        "sensor_available",
        "measurement_age_seconds",
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
