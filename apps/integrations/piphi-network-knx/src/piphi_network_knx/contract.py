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
    "datapoint_value": {"kind": "sensor"},
    "read_datapoint": {"kind": "action"},
    "write_datapoint": {"kind": "action"},
}

COMMANDS: dict[str, dict[str, Any]] = {
    "read_datapoint": {
        "description": "Request the current value of one configured KNX datapoint.",
        "timeout_ms": 10000,
    },
    "write_datapoint": {
        "description": "Write one explicitly allowlisted, typed KNX datapoint.",
        "timeout_ms": 10000,
    },
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "KNX/IP setup",
        "description": "Connect one exclusive KNX/IP tunnel and expose reviewed datapoints.",
        "type": "object",
        "required": ["host", "datapoints"],
        "properties": {
            "host": {"type": "string", "title": "KNX/IP interface address"},
            "port": {
                "type": "integer",
                "title": "Port",
                "default": 3671,
                "minimum": 1,
                "maximum": 65535,
            },
            "alias": {"type": "string", "title": "Installation name", "maxLength": 120},
            "transport": {
                "type": "string",
                "title": "Transport",
                "enum": ["automatic", "tunneling_udp", "tunneling_tcp"],
                "default": "tunneling_udp",
            },
            "allow_writes": {
                "type": "boolean",
                "title": "Enable writes to explicitly writable datapoints",
                "default": False,
            },
            "rate_limit": {
                "type": "integer",
                "title": "Maximum telegrams per second",
                "default": 10,
                "minimum": 1,
                "maximum": 60,
            },
            "datapoints": {
                "type": "array",
                "title": "Reviewed datapoints",
                "maxItems": 256,
                "items": {
                    "type": "object",
                    "required": ["id", "name", "entity_type", "dpt", "state_address"],
                    "properties": {
                        "id": {"type": "string", "pattern": "^[a-z][a-z0-9_-]{0,63}$"},
                        "name": {"type": "string"},
                        "entity_type": {
                            "type": "string",
                            "enum": ["binary_sensor", "sensor", "switch", "light"],
                        },
                        "dpt": {"type": "string", "enum": ["1.001", "5.001", "9.001"]},
                        "state_address": {"type": "string", "title": "Feedback group address"},
                        "command_address": {"type": "string", "title": "Command group address"},
                        "writable": {"type": "boolean", "default": False},
                        "read_on_init": {"type": "boolean", "default": True},
                    },
                },
            },
        },
    },
    "uiSchema": {
        "host": {"placeholder": "192.168.1.50"},
        "datapoints": {"ui:options": {"orderable": False}},
        "allow_writes": {"ui:widget": "checkbox"},
    },
}
