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
    "availability": {"kind": "sensor", "unit": "bool"},
    "node_status": {"kind": "sensor"},
    "switch_state": {"kind": "sensor", "unit": "bool"},
    "level_percent": {"kind": "sensor", "unit": "%"},
    "battery_percent": {"kind": "sensor", "unit": "%"},
    "battery_low": {"kind": "sensor", "unit": "bool"},
    "temperature_c": {"kind": "sensor", "unit": "°C"},
    "humidity_percent": {"kind": "sensor", "unit": "%"},
    "illuminance_lux": {"kind": "sensor", "unit": "lx"},
    "multilevel_sensor_value": {"kind": "sensor"},
    "meter_value": {"kind": "sensor"},
    "power_w": {"kind": "sensor", "unit": "W"},
    "power_kw": {"kind": "sensor", "unit": "kW"},
    "energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "voltage_v": {"kind": "sensor", "unit": "V"},
    "current_a": {"kind": "sensor", "unit": "A"},
    "frequency_hz": {"kind": "sensor", "unit": "Hz"},
    "lock_state": {"kind": "sensor"},
    "thermostat_mode": {"kind": "sensor"},
    "thermostat_setpoint_c": {"kind": "sensor", "unit": "°C"},
    "refresh": {"kind": "action"},
    "ping_node": {"kind": "action"},
    "request_node_interview": {"kind": "action"},
    "reconnect_driver": {"kind": "action"},
    "set_switch": {"kind": "action"},
    "set_level": {"kind": "action"},
    "set_lock": {"kind": "action"},
    "set_thermostat_mode": {"kind": "action"},
    "set_thermostat_setpoint": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {"description": "Refresh this node's values.", "timeout_ms": 120000},
    "ping_node": {"description": "Check whether this node is reachable.", "timeout_ms": 30000},
    "request_node_interview": {"description": "Request a fresh node interview.", "timeout_ms": 120000},
    "reconnect_driver": {"description": "Reconnect the managed Z-Wave driver.", "timeout_ms": 30000},
    "set_switch": {"description": "Set a metadata-declared writable binary switch.", "timeout_ms": 30000},
    "set_level": {"description": "Set a metadata-declared writable multilevel value.", "timeout_ms": 30000},
    "set_lock": {"description": "Set a metadata-declared writable lock mode.", "timeout_ms": 30000},
    "set_thermostat_mode": {"description": "Set an allowed thermostat mode.", "timeout_ms": 30000},
    "set_thermostat_setpoint": {"description": "Set a bounded thermostat setpoint.", "timeout_ms": 30000},
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "PiPhi Network Z-Wave Setup",
        "type": "object",
        "required": [],
        "properties": {
            "network_id": {
                "type": "string",
                "title": "Managed network",
                "enum": ["primary"],
                "default": "primary"
            },
            "alias": {
                "type": "string",
                "title": "Controller alias"
            },
            "event_poll_interval_seconds": {
                "type": "number",
                "title": "Event replay interval",
                "minimum": 0.25,
                "maximum": 30,
                "default": 1
            }
        }
    },
    "uiSchema": {
        "network_id": {"ui:widget": "hidden"},
        "alias": {
            "placeholder": "Home Z-Wave network"
        },
        "event_poll_interval_seconds": {"ui:widget": "number"}
    }
}
