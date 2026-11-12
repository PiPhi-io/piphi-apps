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
    "active_power_w": {
        "kind": "sensor",
        "unit": "W",
        "dashboard": {
            "allowed_widgets": ["stat", "gauge", "line-chart", "external-widget"],
            "default_widget": "gauge",
            "recommended_widgets": ["line-chart", "external-widget"],
        },
    },
    "active_solar_power_w": {"kind": "sensor", "unit": "W"},
    "voltage_l1_v": {"kind": "sensor", "unit": "V"},
    "voltage_l2_v": {"kind": "sensor", "unit": "V"},
    "frequency_hz": {"kind": "sensor", "unit": "Hz"},
    "daily_usage_kwh": {"kind": "sensor", "unit": "kWh"},
    "daily_production_kwh": {"kind": "sensor", "unit": "kWh"},
    "daily_from_grid_kwh": {"kind": "sensor", "unit": "kWh"},
    "daily_to_grid_kwh": {"kind": "sensor", "unit": "kWh"},
    "active_device_count": {"kind": "sensor", "unit": "devices"},
    "always_on_power_w": {"kind": "sensor", "unit": "W"},
    "other_power_w": {"kind": "sensor", "unit": "W"},
    "device_power_w": {"kind": "sensor", "unit": "W"},
    "device_on": {"kind": "sensor", "unit": "bool"},
    "device_daily_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh current power and daily energy from Sense.",
        "timeout_ms": 15000,
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Sense Energy Setup",
        "description": "Connect one Sense account. The integration reuses one authenticated session to respect Sense API limits.",
        "type": "object",
        "required": ["email", "password"],
        "properties": {
            "email": {
                "type": "string",
                "pattern": r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
                "title": "Sense account email",
            },
            "password": {"type": "string", "title": "Sense password"},
            "mfa_code": {
                "type": "string",
                "title": "Current MFA code",
                "description": "Only required when Sense requests multi-factor authentication.",
                "default": "",
            },
            "alias": {"type": "string", "title": "Display name", "default": "Sense Home"},
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Realtime poll interval",
                "minimum": 60,
                "maximum": 3600,
                "default": 60,
            },
            "trend_interval_seconds": {
                "type": "integer",
                "title": "Daily energy refresh interval",
                "minimum": 300,
                "maximum": 86400,
                "default": 900,
            },
        },
    },
    "uiSchema": {
        "email": {"placeholder": "name@example.com", "autocomplete": "username"},
        "password": {"ui:widget": "password", "autocomplete": "current-password"},
        "mfa_code": {"ui:widget": "password", "placeholder": "123456"},
        "alias": {"placeholder": "Sense Home"},
    },
}

MONITOR_CAPABILITIES = [
    "connected", "active_power_w", "active_solar_power_w", "voltage_l1_v",
    "voltage_l2_v", "frequency_hz", "daily_usage_kwh", "daily_production_kwh",
    "daily_from_grid_kwh", "daily_to_grid_kwh", "active_device_count",
    "always_on_power_w", "other_power_w", "refresh",
]

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "sense-monitor",
    "name": "Sense Energy Monitor",
    "device_id": "sense-monitor",
    "entity_type": "energy_monitor",
    "capabilities": MONITOR_CAPABILITIES,
    "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
    "dashboard": {
        "allowed_widgets": ["energy-flow", "gauge", "line-chart", "stat", "external-widget"],
        "default_widget": "energy-flow",
    },
}
