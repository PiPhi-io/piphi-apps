from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health", "diagnostics": "/diagnostics", "discover": "/discover",
    "entities": "/entities", "state": "/state", "config": "/config",
    "config_sync": "/config/sync", "deconfigure": "/deconfigure",
    "ui_config": "/ui-config", "events": "/events", "command": "/command",
}
REQUIRED_ENDPOINTS = ["health", "config", "ui_config"]
CAPABILITIES: dict[str, dict[str, Any]] = {}
COMMANDS: dict[str, dict[str, Any]] = {}
CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Daikin Onecta unavailable",
        "type": "object",
        "description": "This preview is quarantined because no Onecta OAuth or API adapter is implemented. Configuration is disabled.",
        "properties": {},
        "additionalProperties": False,
    },
    "uiSchema": {},
}
