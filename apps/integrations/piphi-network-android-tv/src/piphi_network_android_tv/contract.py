from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "discover": "/discover",
    "pairing_start": "/pairing/start",
    "pairing_finish": "/pairing/{session_id}/finish",
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
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Office Device"
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
