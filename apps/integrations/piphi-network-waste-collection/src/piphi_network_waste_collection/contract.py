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
    "next_collection_date": {"kind": "sensor", "value_kind": "text"},
    "next_collection_type": {"kind": "sensor", "value_kind": "text"},
    "days_until_collection": {"kind": "sensor", "value_kind": "numeric", "unit": "days"},
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
        "title": "Next waste collection",
        "type": "object",
        "required": ["next_collection_date", "collection_type"],
        "properties": {
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "next_collection_date": {"type": "string", "title": "Next pickup date (YYYY-MM-DD)"},
            "collection_type": {"type": "string", "title": "Collection type"},
            "schedule_timezone": {"type": "string", "title": "Time zone"}
        }
    },
    "uiSchema": {
        "alias": {
            "placeholder": "Home collection"
        },
        "next_collection_date": {"placeholder": "2026-09-25"},
        "collection_type": {"placeholder": "Recycling"},
        "schedule_timezone": {"placeholder": "America/New_York"}
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "sensor",
    "capabilities": [
        "connected",
        "next_collection_date",
        "next_collection_type",
        "days_until_collection",
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
