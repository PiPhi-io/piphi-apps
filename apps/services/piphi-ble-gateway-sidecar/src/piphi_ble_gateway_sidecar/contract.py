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
    "service_available": {"kind": "sensor", "unit": "bool"},
    "receiver_healthy": {"kind": "sensor", "unit": "bool"},
    "scanner_state": {"kind": "sensor", "unit": "string"},
    "scan_mode": {"kind": "sensor", "unit": "string"},
    "observations_received_total": {"kind": "sensor", "unit": "count"},
    "observations_deduplicated_total": {"kind": "sensor", "unit": "count"},
    "last_observation_age_ms": {"kind": "sensor", "unit": "ms"},
    "reconnects": {"kind": "sensor", "unit": "count"},
    "queue_depth": {"kind": "sensor", "unit": "count"},
    "queue_capacity": {"kind": "sensor", "unit": "count"},
    "queue_high_water": {"kind": "sensor", "unit": "count"},
    "drops": {"kind": "sensor", "unit": "count"},
    "coalesces": {"kind": "sensor", "unit": "count"},
    "adapter_count": {"kind": "sensor", "unit": "count"},
    "adapter_powered": {"kind": "sensor", "unit": "bool"},
    "adapter_discovering": {"kind": "sensor", "unit": "bool"},
    "rfkill_soft_blocked": {"kind": "sensor", "unit": "bool"},
    "rfkill_hard_blocked": {"kind": "sensor", "unit": "bool"},
    "refresh": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Piphi Ble Gateway Sidecar Setup",
        "type": "object",
        "required": [],
        "properties": {
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "service_name": {
                "type": "string",
                "title": "Service Name"
            }
        }
    },
    "uiSchema": {
        "alias": {
            "placeholder": "Office Device"
        },
        "service_name": {
            "placeholder": "local-helper"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "ble-gateway-service",
    "name": "BLE Gateway Service",
    "device_id": "ble-gateway-service",
    "entity_type": "service",
    "capabilities": [
        "service_available",
        "receiver_healthy",
        "scanner_state",
        "scan_mode",
        "observations_received_total",
        "observations_deduplicated_total",
        "last_observation_age_ms",
        "reconnects",
        "queue_depth",
        "queue_capacity",
        "queue_high_water",
        "drops",
        "coalesces",
        "adapter_count",
        "adapter_powered",
        "adapter_discovering",
        "rfkill_soft_blocked",
        "rfkill_hard_blocked",
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
            "button"
        ],
        "default_widget": "tile"
    }
}
