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
    "presence": {
        "kind": "sensor",
        "unit": "enum"
    },
    "area_id": {"kind": "sensor", "unit": "string"},
    "area_name": {"kind": "sensor", "unit": "string"},
    "estimated_distance_m": {"kind": "sensor", "unit": "m"},
    "distance_raw_m": {"kind": "sensor", "unit": "m"},
    "freshness_seconds": {"kind": "sensor", "unit": "s"},
    "coverage_degraded": {"kind": "sensor", "unit": "bool"},
    "topology_revision": {"kind": "sensor", "unit": "count"},
    "area_switch_reason": {"kind": "sensor", "unit": "string"},
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
        "title": "Piphi Network Bermuda Presence Setup",
        "type": "object",
        "required": ["gateway_url", "api_token", "consumer_id", "selected_device_handles", "receivers"],
        "properties": {
            "gateway_url": {"type": "string", "format": "uri", "title": "BLE gateway URL"},
            "api_token": {"type": "string", "format": "password", "title": "Gateway bearer token"},
            "consumer_id": {"type": "string", "title": "Consumer ID"},
            "selected_device_handles": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "pattern": "^ble_[0-9a-f]{32}$"}},
            "receivers": {"type": "array", "items": {"type": "object", "required": ["receiver_id", "area_id", "area_name"]}},
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 1,
                "maximum": 30
            },
            "consider_home_seconds": {"type": "integer", "minimum": 30, "maximum": 3600},
            "stale_seconds": {"type": "integer", "minimum": 5, "maximum": 300},
            "reference_power_dbm": {"type": "integer", "minimum": -100, "maximum": -20},
            "attenuation_factor": {"type": "number", "minimum": 1, "maximum": 5},
            "smoothing_samples": {"type": "integer", "minimum": 1, "maximum": 20},
            "area_switch_margin_m": {"type": "number", "minimum": 0.1, "maximum": 20},
            "area_switch_samples": {"type": "integer", "minimum": 1, "maximum": 20}
            }
        },
    "uiSchema": {
        "gateway_url": {"placeholder": "https://ble-gateway.local:8443"},
        "api_token": {"ui:widget": "password"},
        "alias": {
            "placeholder": "Office Device"
        },
        "poll_interval_seconds": {
            "placeholder": "30"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "selected-device-template",
    "name": "Selected BLE device",
    "device_id": "selected-device-template",
    "entity_type": "presence_sensor",
    "capabilities": list(CAPABILITIES),
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
