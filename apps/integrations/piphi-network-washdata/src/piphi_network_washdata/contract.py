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
    "available": {"kind": "sensor", "unit": "bool"},
    "stale": {"kind": "sensor", "unit": "bool"},
    "detector_status": {"kind": "sensor"},
    "cycle_state": {"kind": "sensor"},
    "cycle_active": {"kind": "sensor", "unit": "bool"},
    "cycle_started_at": {"kind": "sensor", "optional": True},
    "cycle_finished_at": {"kind": "sensor", "optional": True},
    "cycle_duration_s": {"kind": "sensor", "unit": "s", "optional": True},
    "power_w": {"kind": "sensor", "unit": "W", "optional": True},
    "peak_power_w": {"kind": "sensor", "unit": "W", "optional": True},
    "cycle_energy_kwh": {"kind": "sensor", "unit": "kWh"},
    "lifetime_cycle_count": {"kind": "sensor", "unit": "count"},
    "last_sample_at": {"kind": "sensor", "optional": True},
    "refresh": {"kind": "action", "read_only": True},
}
COMMANDS = {
    "refresh": {"description": "Read one bounded source telemetry page.", "timeout_ms": 10000}
}
CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "WashData cycle monitor",
        "description": "Monitor a Core-authorized appliance power source. This integration cannot control appliance power.",
        "type": "object",
        "properties": {
            "alias": {"type": "string", "title": "Display name", "default": "Appliance cycle"},
            "binding_key": {
                "type": "string",
                "title": "Core source binding key",
                "default": "appliance_power",
            },
            "power_metric": {"type": "string", "title": "Power metric", "default": "power_w"},
            "start_threshold_w": {
                "type": "number",
                "title": "Start threshold",
                "minimum": 0,
                "default": 10,
            },
            "stop_threshold_w": {
                "type": "number",
                "title": "Stop threshold",
                "minimum": 0,
                "default": 5,
            },
            "start_debounce_samples": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 2,
            },
            "stop_debounce_samples": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 3,
            },
            "poll_interval_seconds": {"type": "number", "minimum": 1, "maximum": 300, "default": 5},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            "max_sample_gap_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 86400,
                "default": 900,
            },
        },
        "additionalProperties": False,
    },
    "uiSchema": {"binding_key": {"ui:readonly": True}, "power_metric": {"ui:readonly": True}},
}
ENTITY_TEMPLATE = {
    "entity_type": "appliance_cycle",
    "capabilities": list(CAPABILITIES),
    "dashboard": {"allowed_widgets": ["tile", "stat"], "default_widget": "tile"},
}
