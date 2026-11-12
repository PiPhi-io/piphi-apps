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
    "bridge_snapshot": "/v1/snapshot",
    "bridge_adapters": "/v1/adapters",
    "bridge_config_render": "/v1/config/render",
    "bridge_config_write": "/v1/config/write",
    "bridge_apply": "/v1/apply",
    "bridge_supervisor_status": "/v1/supervisor/status",
    "bridge_supervisor_start": "/v1/supervisor/start",
    "bridge_supervisor_stop": "/v1/supervisor/stop",
    "bridge_supervisor_restart": "/v1/supervisor/restart",
    "bridge_supervisor_logs": "/v1/supervisor/logs",
    "bridge_prerequisites": "/v1/prerequisites",
    "bridge_mqtt_check": "/v1/mqtt/check",
    "bridge_network_map": "/v1/network-map",
}

REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]

CAPABILITIES: dict[str, dict[str, Any]] = {
    "connected": {
        "kind": "sensor",
        "unit": "bool"
    },
    "refresh": {
        "kind": "action"
    },
    "service_available": {
        "kind": "sensor",
        "unit": "bool"
    },
    "bridge_configured": {
        "kind": "sensor",
        "unit": "bool"
    },
    "adapter_detected": {
        "kind": "sensor",
        "unit": "count"
    },
    "render_config": {
        "kind": "action"
    },
    "zigbee_network_topology": {
        "kind": "sensor",
        "unit": "json"
    },
    "refresh_network_map": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "render_config": {
        "description": "Render or write Zigbee2MQTT configuration.yaml.",
        "timeout_ms": 10000
    },
    "refresh_network_map": {
        "description": "Manually scan the Zigbee mesh and refresh its network topology.",
        "timeout_ms": 130000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "Zigbee2MQTT Sidecar Setup",
        "type": "object",
        "required": [
            "serial_port"
        ],
        "properties": {
            "serial_port": {
                "type": "string",
                "title": "Coordinator Port",
                "description": "USB/serial path for the Zigbee coordinator. PiPhi will prefill this when it can detect the adapter."
            },
            "adapter": {
                "type": "string",
                "title": "Adapter Type",
                "description": "Leave blank only if Zigbee2MQTT can auto-detect your coordinator adapter.",
                "enum": ["zstack", "ember", "deconz", "zigate", "zboss"]
            },
            "mqtt_server": {
                "type": "string",
                "title": "MQTT Server",
                "default": "mqtt://127.0.0.1:1883",
                "description": "MQTT broker URL used by Zigbee2MQTT. PiPhi preselects the required MQTT Broker sidecar when it is installed."
            },
            "mqtt_base_topic": {
                "type": "string",
                "title": "MQTT Base Topic",
                "default": "zigbee2mqtt",
                "description": "Root MQTT topic Zigbee2MQTT uses for bridge and device messages."
            },
            "data_path": {
                "type": "string",
                "title": "Zigbee2MQTT Data Path",
                "default": "/app/data",
                "description": "Path inside the sidecar container where Zigbee2MQTT configuration and state are written."
            }
        }
    },
    "uiSchema": {
        "serial_port": {
            "placeholder": "/dev/serial/by-id/usb-... or COM4"
        },
        "adapter": {
            "placeholder": "ember"
        },
        "mqtt_server": {
            "placeholder": "mqtt://127.0.0.1:1883"
        },
        "mqtt_base_topic": {
            "placeholder": "zigbee2mqtt"
        },
        "data_path": {
            "placeholder": "/app/data"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "zigbee2mqtt-bridge",
    "name": "Zigbee2MQTT Bridge",
    "device_id": "zigbee2mqtt-bridge",
    "entity_type": "service",
    "capabilities": [
        "connected",
        "refresh",
        "service_available",
        "bridge_configured",
        "adapter_detected",
        "render_config",
        "zigbee_network_topology",
        "refresh_network_map"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        },
        {
            "id": "render_config",
            "label": "Render Config",
            "kind": "action"
        },
        {
            "id": "refresh_network_map",
            "label": "Scan Network Map",
            "kind": "action"
        }
    ],
    "dashboard": {
        "allowed_widgets": [
            "tile",
            "stat",
            "button",
            "io.piphi.zigbee2mqtt-network-map"
        ],
        "default_widget": "tile"
    }
}
