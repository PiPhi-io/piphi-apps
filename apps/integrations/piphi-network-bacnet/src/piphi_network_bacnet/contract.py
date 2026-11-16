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

SENSOR_CAPABILITIES: dict[str, dict[str, Any]] = {
    "pm2_5_ug_m3": {"kind": "sensor", "unit": "µg/m³"},
    "pm10_ug_m3": {"kind": "sensor", "unit": "µg/m³"},
    "tvoc_ppb": {"kind": "sensor", "unit": "ppb"},
    "tvoc_ug_m3": {"kind": "sensor", "unit": "µg/m³"},
    "temperature_c": {"kind": "sensor", "unit": "°C"},
    "humidity_percent": {"kind": "sensor", "unit": "%"},
    "co2_ppm": {"kind": "sensor", "unit": "ppm"},
    "km20x_module_8_lifespan_percent": {"kind": "sensor", "unit": "%"},
    "km20x_module_9_lifespan_percent": {"kind": "sensor", "unit": "%"},
    "ozone_ppb": {"kind": "sensor", "unit": "ppb"},
    "differential_pressure_pa": {"kind": "sensor", "unit": "Pa"},
    "flow_speed_pressure_pa": {"kind": "sensor", "unit": "Pa"},
    "in_duct_module_lifespan_percent": {"kind": "sensor", "unit": "%"},
    "no2_ppb": {"kind": "sensor", "unit": "ppb"},
    "co_ppm": {"kind": "sensor", "unit": "ppm"},
}

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {"kind": "sensor", "unit": "bool"},
    **SENSOR_CAPABILITIES,
    "refresh": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Perform an immediate read-only refresh of allowlisted BACnet properties.",
        "timeout_ms": 30000,
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Kaiterra SenseEdge Mini BACnet/IP",
        "description": "Configure one explicit same-subnet SenseEdge Mini target. This profile is read-only.",
        "type": "object",
        "required": ["host", "device_instance", "local_address"],
        "properties": {
            "host": {
                "type": "string",
                "format": "ipv4",
                "title": "SenseEdge IPv4 address",
            },
            "port": {
                "type": "integer",
                "minimum": 1,
                "maximum": 65535,
                "default": 47808,
                "title": "BACnet UDP port",
            },
            "device_instance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4194302,
                "title": "SenseEdge BACnet device instance",
            },
            "local_address": {
                "type": "string",
                "title": "Local BACnet IPv4/CIDR",
                "description": "Host interface address, for example 192.168.1.20/24.",
            },
            "local_device_instance": {
                "type": "integer",
                "minimum": 1,
                "maximum": 4194302,
                "default": 4194000,
                "title": "PiPhi BACnet client instance",
            },
            "profile": {
                "type": "string",
                "const": "kaiterra_sensedge_mini",
                "default": "kaiterra_sensedge_mini",
                "title": "Read-only profile",
            },
            "alias": {"type": "string", "title": "Alias"},
            "poll_interval_seconds": {
                "type": "integer",
                "minimum": 30,
                "maximum": 3600,
                "default": 60,
                "title": "Polling interval",
            },
        },
    },
    "uiSchema": {
        "host": {"placeholder": "192.168.1.50"},
        "device_instance": {"placeholder": "1234"},
        "local_address": {"placeholder": "192.168.1.20/24"},
        "alias": {"placeholder": "Office SenseEdge Mini"},
    },
}

PROFILE_ENTITY: dict[str, Any] = {
    "id": "kaiterra-sensedge-mini",
    "name": "Kaiterra SenseEdge Mini",
    "device_id": "kaiterra-sensedge-mini",
    "entity_type": "air_quality_sensor",
    "capabilities": list(CAPABILITIES),
    "available_commands": [
        {"id": "refresh", "label": "Refresh readings", "kind": "action"}
    ],
    "dashboard": {
        "allowed_widgets": ["tile", "stat"],
        "default_widget": "tile",
    },
}
