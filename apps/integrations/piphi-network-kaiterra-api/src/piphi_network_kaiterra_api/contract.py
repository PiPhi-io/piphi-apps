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
    "temperature_c": {
        "kind": "sensor",
        "unit": "C"
    },
    "refresh": {
        "kind": "action"
    },
    "api_rate_limit_remaining": {
        "kind": "sensor",
        "unit": "requests"
    },
    "api_latency_ms": {
        "kind": "sensor",
        "unit": "ms"
    },
    "co2_ppm": {
        "kind": "sensor",
        "unit": "ppm"
    },
    "humidity_percent": {
        "kind": "sensor",
        "unit": "%"
    },
    "pm1_ug_m3": {
        "kind": "sensor",
        "unit": "ug/m3"
    },
    "pm25_ug_m3": {
        "kind": "sensor",
        "unit": "ug/m3"
    },
    "pm10_ug_m3": {
        "kind": "sensor",
        "unit": "ug/m3"
    },
    "tvoc_ppb": {
        "kind": "sensor",
        "unit": "ppb"
    },
    "ozone_ppb": {
        "kind": "sensor",
        "unit": "ppb"
    },
    "sync_cloud": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "sync_cloud": {
        "description": "Synchronize state from the vendor cloud.",
        "timeout_ms": 15000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Network Kaiterra Api Setup",
        "type": "object",
        "required": [
            "device_udid",
            "api_key"
        ],
        "properties": {
            "device_udid": {
                "type": "string",
                "title": "Kaiterra Device UDID"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "base_url": {
                "type": "string",
                "title": "Base URL"
            },
            "api_key": {
                "type": "string",
                "title": "API Key"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 15
            }
        }
    },
    "uiSchema": {
        "device_udid": {
            "placeholder": "00000000-0031-0101-0000-00007e57c0de"
        },
        "alias": {
            "placeholder": "Office Kaiterra"
        },
        "base_url": {
            "placeholder": "https://api.kaiterra.com/v1"
        },
        "api_key": {
            "placeholder": "Kaiterra API key"
        },
        "poll_interval_seconds": {
            "placeholder": "60"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "sensor",
    "capabilities": [
        "connected",
        "temperature_c",
        "refresh",
        "api_rate_limit_remaining",
        "api_latency_ms",
        "co2_ppm",
        "humidity_percent",
        "pm1_ug_m3",
        "pm25_ug_m3",
        "pm10_ug_m3",
        "tvoc_ppb",
        "ozone_ppb",
        "sync_cloud"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        },
        {
            "id": "sync_cloud",
            "label": "Sync Cloud",
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
