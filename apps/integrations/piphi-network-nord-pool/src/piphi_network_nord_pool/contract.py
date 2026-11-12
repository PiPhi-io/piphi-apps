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
    "market_area": {"kind": "sensor", "unit": "text", "value_kind": "text"},
    "current_price_per_kwh": {"kind": "sensor", "unit": "currency/kWh"},
    "next_price_per_kwh": {"kind": "sensor", "unit": "currency/kWh"},
    "price_unit": {"kind": "sensor", "unit": "text", "value_kind": "text"},
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Read the latest published market prices.",
        "timeout_ms": 20000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Nord Pool market area",
        "type": "object",
        "required": [
            "market_area"
        ],
        "properties": {
            "market_area": {
                "type": "string",
                "title": "Market area",
                "description": "Nord Pool bidding zone, for example SE3 or NO1."
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "currency": {
                "type": "string",
                "title": "Currency",
                "enum": ["EUR", "SEK", "NOK", "DKK", "GBP"],
                "default": "EUR"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 900,
                "maximum": 86400,
                "default": 3600
            }
        }
    },
    "uiSchema": {
        "market_area": {
            "placeholder": "SE3"
        },
        "alias": {
            "placeholder": "Home electricity market"
        },
        "poll_interval_seconds": {
            "placeholder": "3600"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Nord Pool market",
    "device_id": "demo-device",
    "entity_type": "energy_market",
    "capabilities": [
        "connected",
        "market_area",
        "current_price_per_kwh",
        "next_price_per_kwh",
        "price_unit",
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
            "line-chart",
            "external-widget"
        ],
        "default_widget": "stat"
    }
}
