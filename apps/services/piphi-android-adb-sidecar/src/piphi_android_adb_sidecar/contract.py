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
    "adb_snapshot": "/v1/adb/snapshot",
    "adb_reconnect": "/v1/adb/reconnect",
    "adb_execute": "/v1/adb/execute",
}

REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {
        "kind": "sensor",
        "unit": "bool"
    },
    "authorized": {"kind": "sensor", "unit": "bool"},
    "lifecycle": {"kind": "sensor", "unit": "string"},
    "service_available": {"kind": "sensor", "unit": "bool"},
    "device_manufacturer": {"kind": "sensor", "unit": "string"},
    "device_model": {"kind": "sensor", "unit": "string"},
    "android_release": {"kind": "sensor", "unit": "string"},
    "android_sdk": {"kind": "sensor", "unit": "string"},
    "queue_depth": {"kind": "sensor", "unit": "count"},
    "queue_capacity": {"kind": "sensor", "unit": "count"},
    "queue_high_water_mark": {"kind": "sensor", "unit": "count"},
    "reconnect_count": {"kind": "sensor", "unit": "count"},
    "request_success_count": {"kind": "sensor", "unit": "count"},
    "request_failure_count": {"kind": "sensor", "unit": "count"},
    "timeout_count": {"kind": "sensor", "unit": "count"},
    "transport_error_count": {"kind": "sensor", "unit": "count"},
    "operation_duration_ms": {"kind": "sensor", "unit": "ms"},
}

COMMANDS: dict[str, dict[str, Any]] = {}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Android Adb Sidecar Setup",
        "type": "object",
        "required": [
            "host"
        ],
        "properties": {
            "host": {
                "type": "string",
                "title": "Host"
            },
            "port": {
                "type": "integer",
                "title": "ADB port",
                "default": 5555,
                "minimum": 1,
                "maximum": 65535
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "service_name": {
                "type": "string",
                "title": "Service Name"
            },
            "queue_capacity": {
                "type": "integer",
                "title": "Command queue capacity",
                "default": 16,
                "minimum": 1,
                "maximum": 100
            },
            "connect_timeout_ms": {
                "type": "integer",
                "title": "Connect timeout (ms)",
                "default": 5000,
                "minimum": 500,
                "maximum": 30000
            },
            "operation_timeout_ms": {
                "type": "integer",
                "title": "Operation timeout (ms)",
                "default": 5000,
                "minimum": 100,
                "maximum": 30000
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "port": {
            "placeholder": "5555"
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
    "id": "android-adb-service",
    "name": "Android ADB Service",
    "device_id": "android-adb-service",
    "entity_type": "service",
    "capabilities": [
        *CAPABILITIES.keys()
    ],
    "available_commands": [],
    "dashboard": {
        "allowed_widgets": [
            "tile",
            "stat",
            "button"
        ],
        "default_widget": "tile"
    }
}
