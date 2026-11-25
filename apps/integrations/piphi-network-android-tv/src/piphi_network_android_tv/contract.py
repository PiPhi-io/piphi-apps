from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "discover": "/discover",
    "pairing_start": "/pairing/start",
    "pairing_finish": "/pairing/{session_id}/finish",
    "adb_pairing": "/pairing/adb",
    "forget_credentials": "/pairing/credentials/{config_id}",
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
    "authenticated": {"kind": "sensor", "unit": "bool"},
    "reauth_required": {"kind": "sensor", "unit": "bool"},
    "power_on": {"kind": "sensor", "unit": "bool"},
    "current_app_id": {"kind": "sensor", "unit": "string"},
    "volume_level_percent": {"kind": "sensor", "unit": "%"},
    "muted": {"kind": "sensor", "unit": "bool"},
    "manufacturer": {"kind": "sensor", "unit": "string"},
    "model": {"kind": "sensor", "unit": "string"},
    "software_version": {"kind": "sensor", "unit": "string"},
    "transport_type": {"kind": "sensor", "unit": "string"},
    "adb_authorized": {"kind": "sensor", "unit": "bool"},
    "android_version": {"kind": "sensor", "unit": "string"},
    "android_api_level": {"kind": "sensor", "unit": "string"},
    "sidecar_queue_depth": {"kind": "sensor", "unit": "commands"},
    "sidecar_queue_capacity": {"kind": "sensor", "unit": "commands"},
    "sidecar_reconnect_count": {"kind": "sensor", "unit": "count"},
    "sidecar_command_timeout_count": {"kind": "sensor", "unit": "count"},
    "sidecar_last_error_code": {"kind": "sensor", "unit": "string"},
    "refresh": {
        "kind": "action"
    },
    "send_key": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "send_key": {
        "description": "Send one allow-listed short key press.",
        "timeout_ms": 5000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Network Android Tv Setup",
        "type": "object",
        "required": [
            "host",
            "transport"
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
            "transport": {
                "type": "string",
                "title": "Transport",
                "enum": ["remote_v2", "adb"],
                "default": "remote_v2"
            },
            "enable_controls": {
                "type": "boolean",
                "title": "Enable allow-listed remote controls",
                "default": False
            },
            "adb_port": {
                "type": "integer",
                "title": "ADB port",
                "minimum": 1,
                "maximum": 65535,
                "default": 5555
            },
            "adb_queue_capacity": {
                "type": "integer",
                "title": "ADB queue capacity",
                "minimum": 1,
                "maximum": 100,
                "default": 16
            },
            "adb_connect_timeout_ms": {
                "type": "integer",
                "title": "ADB connect timeout (ms)",
                "minimum": 500,
                "maximum": 30000,
                "default": 5000
            },
            "adb_operation_timeout_ms": {
                "type": "integer",
                "title": "ADB operation timeout (ms)",
                "minimum": 100,
                "maximum": 30000,
                "default": 5000
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
        "transport": {
            "help": "Remote v2 is the default. Select ADB only for a separately authorized network ADB target."
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "television",
    "capabilities": [
        "connected",
        "authenticated",
        "reauth_required",
        "power_on",
        "current_app_id",
        "volume_level_percent",
        "muted",
        "manufacturer",
        "model",
        "software_version",
        "transport_type",
        "adb_authorized",
        "android_version",
        "android_api_level",
        "sidecar_queue_depth",
        "sidecar_queue_capacity",
        "sidecar_reconnect_count",
        "sidecar_command_timeout_count",
        "sidecar_last_error_code",
        "refresh",
        "send_key"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        },
        {
            "id": "send_key",
            "label": "Send key",
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
