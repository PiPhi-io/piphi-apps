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
    "camera_count": {"kind": "sensor", "unit": "cameras"},
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh camera and NVR discovery and state.",
        "timeout_ms": 45000,
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Reolink camera or NVR setup",
        "type": "object",
        "required": ["host", "username", "password"],
        "properties": {
            "host": {"type": "string", "title": "Camera or NVR address"},
            "username": {"type": "string", "title": "Username"},
            "password": {"type": "string", "title": "Password", "format": "password"},
            "port": {
                "type": "integer",
                "title": "API port",
                "minimum": 1,
                "maximum": 65535,
            },
            "use_https": {"type": "boolean", "title": "Use HTTPS"},
            "alias": {"type": "string", "title": "Display name"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Polling interval",
                "minimum": 10,
                "maximum": 3600,
                "default": 30,
            },
        },
    },
    "uiSchema": {
        "host": {"placeholder": "192.168.1.50"},
        "username": {"placeholder": "piphi"},
        "password": {"ui:widget": "password"},
        "port": {"placeholder": "80"},
        "alias": {"placeholder": "Front cameras"},
    },
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "reolink-connection",
    "name": "Reolink connection",
    "device_id": "reolink-connection",
    "entity_type": "camera",
    "capabilities": ["connected", "camera_count", "refresh"],
    "available_commands": [
        {"id": "refresh", "label": "Refresh", "kind": "action"},
    ],
    "dashboard": {
        "allowed_widgets": ["tile", "stat", "button"],
        "default_widget": "tile",
    },
}
