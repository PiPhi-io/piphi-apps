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
    "power": {"kind": "sensor", "unit": "bool", "optional": True},
    "hvac_mode": {"kind": "sensor", "optional": True},
    "indoor_temperature_c": {"kind": "sensor", "unit": "C", "optional": True},
    "target_temperature_c": {"kind": "sensor", "unit": "C", "optional": True},
    "refresh": {"kind": "action", "read_only": True},
    "set_target_temperature": {"kind": "action", "opt_in": True},
}
COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh all climate state for this account.",
        "timeout_ms": 20000,
    },
    "set_target_temperature": {
        "description": "Set one validated climate target temperature when explicitly enabled.",
        "timeout_ms": 20000,
    },
}
CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Daikin Onecta account setup",
        "description": "OAuth credentials are authored and refreshed by PiPhi Core.",
        "type": "object",
        "required": ["oauth_subject", "access_token"],
        "properties": {
            "oauth_subject": {"type": "string", "title": "OAuth account subject"},
            "access_token": {
                "type": "string",
                "title": "Core-managed access token",
                "format": "password",
            },
            "alias": {"type": "string", "title": "Display name"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Polling interval",
                "minimum": 300,
                "maximum": 3600,
                "default": 900,
            },
            "enable_climate_control": {
                "type": "boolean",
                "title": "Enable target-temperature control",
                "default": False,
            },
        },
        "additionalProperties": False,
    },
    "uiSchema": {
        "oauth_subject": {"ui:readonly": True},
        "access_token": {"ui:widget": "password", "ui:readonly": True},
        "alias": {"placeholder": "Home climate"},
    },
}
ENTITY_TEMPLATE: dict[str, Any] = {
    "entity_type": "climate",
    "capabilities": list(CAPABILITIES),
    "dashboard": {
        "allowed_widgets": ["tile", "stat", "button"],
        "default_widget": "tile",
    },
}
