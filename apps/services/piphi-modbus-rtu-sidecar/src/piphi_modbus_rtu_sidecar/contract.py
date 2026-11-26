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
    "modbus_snapshot": "/v1/modbus/snapshot",
    "modbus_events": "/v1/modbus/events",
    "modbus_refresh": "/v1/modbus/refresh",
    "modbus_write": "/v1/modbus/write",
    "modbus_write_coils": "/v1/modbus/write-coils",
}

REQUIRED_ENDPOINTS = ["health", "config"]

CAPABILITIES: dict[str, dict[str, Any]] = {}

COMMANDS: dict[str, dict[str, Any]] = {}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Modbus Rtu Sidecar Setup",
        "type": "object",
        "required": [
            "serial_port", "registers"
        ],
        "properties": {
            "serial_port": {"type": "string", "title": "Stable serial adapter path"},
            "serial_mode": {"type": "string", "enum": ["rtu", "ascii"]},
            "baud_rate": {"type": "integer", "minimum": 1200, "maximum": 921600},
            "parity": {"type": "string", "enum": ["N", "E", "O"]},
            "stop_bits": {"type": "integer", "enum": [1, 2]},
            "data_bits": {"type": "integer", "enum": [7, 8]},
            "profile_id": {"type": "string"},
            "profile_version": {"type": "string"},
            "profile_sha256": {"type": "string"},
            "profile_signature": {"type": "string"},
            "writes_enabled": {"type": "boolean", "default": False},
            "registers": {"type": "array", "minItems": 1}
        }
    },
    "uiSchema": {
        "serial_port": {"placeholder": "/dev/serial/by-id/usb-vendor_adapter"},
        "profile_signature": {"ui:widget": "password"}
    }
}
