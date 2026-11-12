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
    "simulation_mode": {"kind": "sensor", "unit": "bool"},
    "print_status": {"kind": "sensor"},
    "print_progress_percent": {"kind": "sensor", "unit": "%"},
    "remaining_time_minutes": {"kind": "sensor", "unit": "min"},
    "current_layer": {"kind": "sensor"},
    "total_layers": {"kind": "sensor"},
    "nozzle_temperature_c": {"kind": "sensor", "unit": "C"},
    "target_nozzle_temperature_c": {"kind": "sensor", "unit": "C"},
    "bed_temperature_c": {"kind": "sensor", "unit": "C"},
    "target_bed_temperature_c": {"kind": "sensor", "unit": "C"},
    "refresh": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Request a full printer status at most once every five minutes.",
        "timeout_ms": 5000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Network Bambu Lab Setup",
        "type": "object",
        "required": [],
        "description": "For a real printer, enter host, serial, LAN access code, and acknowledge Developer Mode. For testing, choose Simulation mode without real credentials.",
        "properties": {
            "simulation_mode": {
                "type": "boolean",
                "title": "Simulated printer (testing only)",
                "description": "Generates sample print reports for dashboard testing; never contacts a printer."
            },
            "host": {
                "type": "string",
                "title": "Printer LAN IPv4 address",
                "description": "A private LAN address; cloud endpoints are not supported."
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "serial": {
                "type": "string",
                "title": "Printer serial number"
            },
            "access_code": {
                "type": "string",
                "title": "LAN access code",
                "format": "password"
            },
            "developer_mode_acknowledged": {
                "type": "boolean",
                "title": "I enabled Developer Mode on this printer and understand Bambu's security warning"
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Printer"
        },
        "serial": {
            "placeholder": "Printer serial"
        },
        "access_code": {
            "ui:widget": "password"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Bambu printer",
    "device_id": "demo-device",
    "entity_type": "sensor",
    "capabilities": [
        "connected",
        "simulation_mode",
        "print_status",
        "print_progress_percent",
        "remaining_time_minutes",
        "current_layer",
        "total_layers",
        "nozzle_temperature_c",
        "target_nozzle_temperature_c",
        "bed_temperature_c",
        "target_bed_temperature_c",
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
            "external-widget"
        ],
        "default_widget": "external-widget"
    }
}
