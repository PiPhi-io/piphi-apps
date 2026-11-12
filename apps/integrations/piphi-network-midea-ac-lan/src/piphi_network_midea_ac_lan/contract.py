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
    "power": {"kind": "actuator", "unit": "bool"},
    "hvac_mode": {"kind": "actuator", "value_kind": "enum"},
    "hvac_action": {"kind": "sensor", "value_kind": "enum"},
    "target_temperature_c": {"kind": "actuator", "value_kind": "numeric", "unit": "°C"},
    "indoor_temperature_c": {"kind": "sensor", "unit": "°C"},
    "outdoor_temperature_c": {"kind": "sensor", "unit": "°C"},
    "fan_speed_percent": {"kind": "sensor", "unit": "%"},
    "fan_mode": {"kind": "actuator", "value_kind": "enum"},
    "fan_modes_supported": {"kind": "sensor", "value_kind": "text"},
    "swing_mode": {"kind": "actuator", "value_kind": "enum"},
    "swing_modes_supported": {"kind": "sensor", "value_kind": "text"},
    "preset_mode": {"kind": "actuator", "value_kind": "enum"},
    "preset_modes_supported": {"kind": "sensor", "value_kind": "text"},
    "refresh": {"kind": "action"},
    "set_power": {"kind": "action"},
    "set_hvac_mode": {"kind": "action"},
    "set_target_temperature": {"kind": "action"},
    "set_fan_mode": {"kind": "action"},
    "set_swing_mode": {"kind": "action"},
    "set_preset_mode": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "set_power": {
        "description": "Turn the configured air conditioner on or off.",
        "args_schema": {
            "power": {
                "type": "boolean",
                "label": "Power",
                "semantic": "climate.power",
                "required": True,
            }
        },
        "timeout_ms": 10000,
    },
    "set_hvac_mode": {
        "description": "Set a supported HVAC operating mode.",
        "args_schema": {
            "mode": {
                "type": "string",
                "label": "HVAC mode",
                "semantic": "climate.hvac_mode",
                "required": True,
                "options": ["auto", "cool", "heat", "dry", "fan_only"],
            }
        },
        "timeout_ms": 10000,
    },
    "set_target_temperature": {
        "description": "Set the target temperature within the device-reported range.",
        "args_schema": {
            "temperature": {
                "type": "number",
                "label": "Target temperature",
                "semantic": "climate.target_temperature",
                "required": True,
                "minimum": 16,
                "maximum": 30,
                "step": 0.5,
                "unit": "°C",
            }
        },
        "timeout_ms": 10000,
    },
    "set_fan_mode": {
        "description": "Set a fan speed reported as supported by the device.",
        "args_schema": {
            "fan_mode": {
                "type": "string",
                "label": "Fan mode",
                "semantic": "climate.fan_mode",
                "required": True,
                "options": ["auto", "silent", "low", "medium", "high", "max"],
            }
        },
        "timeout_ms": 10000,
    },
    "set_swing_mode": {
        "description": "Set a louver swing mode reported as supported by the device.",
        "args_schema": {
            "swing_mode": {
                "type": "string",
                "label": "Swing mode",
                "semantic": "climate.swing_mode",
                "required": True,
                "options": ["off", "vertical", "horizontal", "both"],
            }
        },
        "timeout_ms": 10000,
    },
    "set_preset_mode": {
        "description": "Activate a supported comfort preset or clear the active preset.",
        "args_schema": {
            "preset_mode": {
                "type": "string",
                "label": "Preset",
                "semantic": "climate.preset_mode",
                "required": True,
                "options": ["none", "sleep", "eco", "boost", "away"],
            }
        },
        "timeout_ms": 10000,
    },
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Network Midea Ac Lan Setup",
        "type": "object",
        "required": [
            "host"
        ],
        "properties": {
            "host": {
                "type": "string",
                "title": "Host",
                "description": "IP address or hostname of the Midea air conditioner"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "port": {
                "type": "integer",
                "title": "Port",
                "minimum": 1,
                "maximum": 65535,
                "default": 6444
            },
            "midea_device_id": {
                "type": "integer",
                "title": "Device ID",
                "description": "Optional device ID from msmart-ng discovery"
            },
            "token": {
                "type": "string",
                "title": "Local token",
                "description": "Optional V3 token; configure together with the local key"
            },
            "key": {
                "type": "string",
                "title": "Local key",
                "description": "Optional V3 key; configure together with the local token"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 5,
                "maximum": 3600,
                "default": 30
            },
            "controls_enabled": {
                "type": "boolean",
                "title": "Enable controls",
                "description": "Allow PiPhi dashboards and automations to change this device",
                "default": False
            }
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Office Device"
        },
        "port": {"placeholder": "6444"},
        "midea_device_id": {"placeholder": "Device ID from discovery"},
        "token": {"ui:widget": "password"},
        "key": {"ui:widget": "password"},
        "poll_interval_seconds": {"placeholder": "30"}
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "climate",
    "capabilities": [
        "connected",
        "power",
        "hvac_mode",
        "hvac_action",
        "target_temperature_c",
        "indoor_temperature_c",
        "outdoor_temperature_c",
        "fan_speed_percent",
        "fan_mode",
        "fan_modes_supported",
        "swing_mode",
        "swing_modes_supported",
        "preset_mode",
        "preset_modes_supported",
        "set_power",
        "set_hvac_mode",
        "set_target_temperature",
        "set_fan_mode",
        "set_swing_mode",
        "set_preset_mode",
        "refresh"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        },
        {
            "id": "set_power",
            "label": "Set power",
            "kind": "action"
        },
        {
            "id": "set_hvac_mode",
            "label": "Set HVAC mode",
            "kind": "action"
        },
        {
            "id": "set_target_temperature",
            "label": "Set target temperature",
            "kind": "action"
        },
        {
            "id": "set_fan_mode",
            "label": "Set fan mode",
            "kind": "action"
        },
        {
            "id": "set_swing_mode",
            "label": "Set swing mode",
            "kind": "action"
        },
        {
            "id": "set_preset_mode",
            "label": "Set preset mode",
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
