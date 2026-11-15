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
    "holding_register_value": {"kind": "sensor", "value_kind": "numeric"},
    "point_value": {"kind": "sensor", "value_kind": "numeric_or_boolean"},
    "power": {"kind": "sensor", "unit": "bool"},
    "brightness_percent": {"kind": "sensor", "unit": "%"},
    "color_temp_percent": {"kind": "sensor", "unit": "%"},
    "fan_speed_percent": {"kind": "sensor", "unit": "%"},
    "oscillating": {"kind": "sensor", "unit": "bool"},
    "position_percent": {"kind": "sensor", "unit": "%"},
    "movement_state": {"kind": "sensor", "unit": "string"},
    "temperature_c": {"kind": "sensor", "unit": "C"},
    "target_temperature_c": {"kind": "sensor", "unit": "C"},
    "mode": {"kind": "sensor", "unit": "string"},
    "refresh": {
        "kind": "action"
    },
    "set_value": {"kind": "action"},
    "run_coil_command": {"kind": "action"},
    **{
        command: {"kind": "action"}
        for command in (
            "turn_on",
            "turn_off",
            "set_brightness",
            "set_color_temp",
            "set_mode",
            "set_fan_speed",
            "set_oscillate",
            "open_cover",
            "close_cover",
            "stop_cover",
            "set_cover_position",
            "set_temperature",
        )
    },
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 12000
    },
    "set_value": {
        "description": "Set a profile-declared writable point within its bounds.",
        "timeout_ms": 30000
    },
    "run_coil_command": {
        "description": "Run a reviewed profile-declared multiple-coil command.",
        "timeout_ms": 90000,
        "args_schema": {"command_id": {"type": "string", "required": True}},
    },
    "turn_on": {"description": "Turn on a profile-composed device.", "timeout_ms": 30000},
    "turn_off": {"description": "Turn off a profile-composed device.", "timeout_ms": 30000},
    "set_brightness": {
        "description": "Set profile-composed light brightness.",
        "timeout_ms": 30000,
        "args_schema": {"brightness": {"type": "number", "required": True, "minimum": 0, "maximum": 100, "unit": "%"}},
    },
    "set_color_temp": {
        "description": "Set profile-composed light color temperature.",
        "timeout_ms": 30000,
        "args_schema": {"color_temp": {"type": "number", "required": True, "minimum": 0, "maximum": 100, "unit": "%"}},
    },
    "set_mode": {
        "description": "Set a reviewed profile mode.",
        "timeout_ms": 30000,
        "args_schema": {"mode": {"type": "string", "required": True}},
    },
    "set_fan_speed": {
        "description": "Set profile-composed fan speed.",
        "timeout_ms": 30000,
        "args_schema": {"speed": {"type": "number", "required": True, "minimum": 0, "maximum": 100, "unit": "%"}},
    },
    "set_oscillate": {
        "description": "Set profile-composed fan oscillation.",
        "timeout_ms": 30000,
        "args_schema": {"oscillating": {"type": "boolean", "required": True}},
    },
    "open_cover": {"description": "Open a profile-composed cover.", "timeout_ms": 30000},
    "close_cover": {"description": "Close a profile-composed cover.", "timeout_ms": 30000},
    "stop_cover": {"description": "Stop a profile-composed cover.", "timeout_ms": 30000},
    "set_cover_position": {
        "description": "Set profile-composed cover position.",
        "timeout_ms": 30000,
        "args_schema": {"position": {"type": "number", "required": True, "minimum": 0, "maximum": 100, "unit": "%"}},
    },
    "set_temperature": {
        "description": "Set profile-composed target temperature.",
        "timeout_ms": 30000,
        "args_schema": {"temperature_c": {"type": "number", "required": True, "unit": "C"}},
    },
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Modbus TCP register",
        "type": "object",
        "required": ["host", "register_address"],
        "properties": {
            "host": {
                "type": "string",
                "title": "Host"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "register_address": {"type": "integer", "title": "Zero-based holding register address", "minimum": 0, "maximum": 65535},
            "unit_id": {"type": "integer", "title": "Modbus unit ID", "minimum": 1, "maximum": 247},
            "poll_interval_seconds": {"type": "integer", "title": "Default poll interval (seconds; 0 disables polling)", "minimum": 0, "maximum": 86400},
            "inter_message_delay_ms": {"type": "integer", "title": "Inter-message delay (milliseconds)", "minimum": 0, "maximum": 5000},
            "poll_jitter_percent": {"type": "number", "title": "Poll jitter (%)", "minimum": 0, "maximum": 50},
            "poll_backoff_max_seconds": {"type": "integer", "title": "Maximum failure backoff (seconds)", "minimum": 1, "maximum": 86400}
        }
    },
    "uiSchema": {
        "host": {
            "placeholder": "192.168.1.50"
        },
        "alias": {
            "placeholder": "Meter register"
        },
        "register_address": {"placeholder": "0"},
        "unit_id": {"placeholder": "1"},
        "poll_interval_seconds": {"placeholder": "300"},
        "inter_message_delay_ms": {"placeholder": "0"},
        "poll_jitter_percent": {"placeholder": "10"},
        "poll_backoff_max_seconds": {"placeholder": "300"}
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "demo-device",
    "name": "Demo Device",
    "device_id": "demo-device",
    "entity_type": "modbus_device",
    "capabilities": list(CAPABILITIES),
    "available_commands": [
        {
            "id": command_id,
            "label": command_id.replace("_", " ").title(),
            "kind": "action",
            **(
                {"args_schema": definition["args_schema"]}
                if definition.get("args_schema")
                else {}
            ),
        }
        for command_id, definition in COMMANDS.items()
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
