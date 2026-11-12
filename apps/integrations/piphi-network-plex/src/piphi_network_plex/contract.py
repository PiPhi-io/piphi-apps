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
    "provider_instances": "/provider/instances",
    "provider_collections": "/provider/{instance_id}/collections",
    "provider_items": "/provider/{instance_id}/items",
    "provider_resolve": "/provider/{instance_id}/resolve",
    "provider_actions": "/provider/{instance_id}/actions",
}

REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {
        "kind": "sensor",
        "unit": "bool"
    },
    "server_count": {
        "kind": "sensor",
        "unit": "servers"
    },
    "refresh": {
        "kind": "action"
    },
    "active_sessions": {
        "kind": "sensor",
        "unit": "sessions"
    },
    "transcode_sessions": {
        "kind": "sensor",
        "unit": "sessions"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Network Plex Setup",
        "type": "object",
        "required": [],
        "properties": {
            "host": {
                "type": "string",
                "title": "Server host (optional)"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "base_url": {
                "type": "string",
                "title": "Server URL (optional)"
            },
            "token": {
                "type": "string",
                "title": "Plex token"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 5
            },
            "include_remote_servers": {
                "type": "boolean",
                "title": "Include shared and remote servers",
                "default": True
            },
            "simulation_mode": {
                "type": "boolean",
                "title": "Use simulated Plex server",
                "default": False
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
        "base_url": {
            "placeholder": "https://api.vendor.example"
        },
        "token": {
            "ui:widget": "password",
            "placeholder": "X-Plex-Token"
        },
        "poll_interval_seconds": {
            "placeholder": "60"
        },
        "simulation_mode": {
            "ui:help": "Developer mode: use deterministic libraries and playback sessions without contacting Plex."
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "plex-server",
    "name": "Plex Media Server",
    "device_id": "plex-server",
    "device_class": "media_server",
    "entity_type": "media_library",
    "capabilities": [
        "connected",
        "server_count",
        "refresh",
        "active_sessions",
        "transcode_sessions"
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
            "button",
            "external-widget"
        ],
        "default_widget": "tile"
    }
}
