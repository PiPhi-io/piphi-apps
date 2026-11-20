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
    "available": {"kind": "sensor", "unit": "bool"},
    "stale": {"kind": "sensor", "unit": "bool"},
    "privacy_mode": {"kind": "sensor", "unit": "bool", "optional": True},
    "camera_enabled": {"kind": "sensor", "unit": "bool", "optional": True},
    "signal_strength": {"kind": "sensor", "unit": "dBm", "optional": True},
    "refresh": {"kind": "action", "read_only": True},
}
COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {"description": "Refresh read-only camera state.", "timeout_ms": 20000}
}
CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Tapo camera setup",
        "type": "object",
        "required": ["host", "username", "password"],
        "properties": {
            "host": {"type": "string", "title": "Camera address"},
            "username": {"type": "string", "title": "Camera account username"},
            "password": {"type": "string", "title": "Camera account password", "format": "password"},
            "alias": {"type": "string", "title": "Display name"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Polling interval",
                "minimum": 60,
                "maximum": 3600,
                "default": 60,
            },
        },
        "additionalProperties": False,
    },
    "uiSchema": {
        "host": {"placeholder": "192.0.2.10"},
        "username": {"placeholder": "camera@example.invalid"},
        "password": {"ui:widget": "password"},
        "alias": {"placeholder": "Front camera"},
    },
}
ENTITY_TEMPLATE: dict[str, Any] = {
    "entity_type": "camera",
    "capabilities": list(CAPABILITIES),
    "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
    "dashboard": {"allowed_widgets": ["tile", "stat", "button"], "default_widget": "tile"},
}
