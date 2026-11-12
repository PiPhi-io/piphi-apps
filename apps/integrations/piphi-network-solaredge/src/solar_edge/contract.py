from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health", "diagnostics": "/diagnostics", "discover": "/discover",
    "entities": "/entities", "state": "/state", "config": "/config",
    "config_sync": "/config/sync", "deconfigure": "/deconfigure",
    "ui_config": "/ui-config", "events": "/events", "command": "/command",
}
REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {"kind": "sensor", "unit": "bool"},
    "production_power_w": {"kind": "sensor", "unit": "W", "dashboard": {
        "allowed_widgets": ["stat", "gauge", "line-chart", "external-widget"],
        "default_widget": "gauge", "recommended_widgets": ["line-chart", "external-widget"],
    }},
    "consumption_power_w": {"kind": "sensor", "unit": "W"},
    "grid_power_w": {"kind": "sensor", "unit": "W"},
    "battery_power_w": {"kind": "sensor", "unit": "W"},
    "battery_soc_percent": {"kind": "sensor", "unit": "%"},
    "today_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "month_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "year_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "lifetime_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "lifetime_revenue": {"kind": "sensor", "unit": "currency"},
    "refresh": {"kind": "action"},
}

COMMANDS = {"refresh": {"description": "Refresh SolarEdge power flow and energy totals.", "timeout_ms": 15000}}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "SolarEdge Monitoring Setup",
        "description": "Connect one SolarEdge Monitoring site with its Site ID and API key. Legacy V1 access is scheduled for deprecation on November 1, 2026.",
        "type": "object",
        "required": ["site_id", "api_key"],
        "properties": {
            "site_id": {"type": "integer", "minimum": 1, "title": "Site ID"},
            "api_key": {"type": "string", "format": "password", "title": "Monitoring API key"},
            "alias": {"type": "string", "title": "Display name", "default": "SolarEdge site"},
            "poll_interval_seconds": {"type": "integer", "title": "Power-flow refresh interval", "minimum": 600, "maximum": 86400, "default": 900},
            "summary_interval_seconds": {"type": "integer", "title": "Energy-summary refresh interval", "minimum": 3600, "maximum": 86400, "default": 3600},
        },
    },
    "uiSchema": {
        "site_id": {"placeholder": "1234567"},
        "api_key": {"ui:widget": "password", "placeholder": "SolarEdge API key"},
        "alias": {"placeholder": "Home solar"},
    },
}

SITE_CAPABILITIES = list(CAPABILITIES)
FALLBACK_ENTITY: dict[str, Any] = {
    "id": "solaredge-site", "name": "SolarEdge site", "device_id": "solaredge-site",
    "entity_type": "solar_energy_system", "capabilities": SITE_CAPABILITIES,
    "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
    "dashboard": {"allowed_widgets": ["energy-flow", "gauge", "line-chart", "stat", "external-widget"], "default_widget": "energy-flow"},
}
