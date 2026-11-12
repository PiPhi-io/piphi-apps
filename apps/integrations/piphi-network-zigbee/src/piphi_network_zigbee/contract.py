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
    "refresh": {
        "kind": "action"
    },
    "availability": {
        "kind": "sensor",
        "unit": "bool"
    },
    "linkquality": {
        "kind": "sensor",
        "unit": "lqi"
    },
    "action": {
        "kind": "sensor",
        "unit": "string"
    },
    "temperature_c": {
        "kind": "sensor",
        "unit": "C"
    },
    "humidity_percent": {
        "kind": "sensor",
        "unit": "%"
    },
    "battery_percent": {
        "kind": "sensor",
        "unit": "%"
    },
    "battery_low": {
        "kind": "sensor",
        "unit": "bool"
    },
    "occupancy": {
        "kind": "sensor",
        "unit": "bool"
    },
    "contact_open": {
        "kind": "sensor",
        "unit": "bool"
    },
    "illuminance_lux": {
        "kind": "sensor",
        "unit": "lx"
    },
    "pressure_hpa": {
        "kind": "sensor",
        "unit": "hPa"
    },
    "voltage_v": {
        "kind": "sensor",
        "unit": "V"
    },
    "current_a": {
        "kind": "sensor",
        "unit": "A"
    },
    "power_w": {
        "kind": "sensor",
        "unit": "W"
    },
    "energy_kwh": {
        "kind": "sensor",
        "unit": "kWh"
    },
    "tamper": {
        "kind": "sensor",
        "unit": "bool"
    },
    "water_leak": {
        "kind": "sensor",
        "unit": "bool"
    },
    "smoke": {
        "kind": "sensor",
        "unit": "bool"
    },
    "gas": {
        "kind": "sensor",
        "unit": "bool"
    },
    "carbon_monoxide": {
        "kind": "sensor",
        "unit": "bool"
    },
    "state": {
        "kind": "actuator",
        "unit": "bool"
    },
    "brightness_percent": {
        "kind": "actuator",
        "unit": "%"
    },
    "color_temperature_mired": {
        "kind": "actuator",
        "unit": "mired"
    },
    "position_percent": {
        "kind": "actuator",
        "unit": "%"
    },
    "set_state": {
        "kind": "action"
    },
    "set_brightness": {
        "kind": "action"
    },
    "set_color_temperature": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "set_state": {
        "description": "Set an on/off style Zigbee device state.",
        "timeout_ms": 5000
    },
    "set_brightness": {
        "description": "Set a dimmable Zigbee device brightness percentage.",
        "timeout_ms": 5000
    },
    "set_color_temperature": {
        "description": "Set a tunable white Zigbee device color temperature.",
        "timeout_ms": 10000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "PiPhi Network Zigbee Setup",
        "type": "object",
        "required": [
            "friendly_name"
        ],
        "properties": {
            "friendly_name": {
                "type": "string",
                "title": "Zigbee2MQTT Friendly Name"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "ieee_address": {
                "type": "string",
                "title": "IEEE Address"
            },
            "model_id": {
                "type": "string",
                "title": "Model"
            },
            "vendor": {
                "type": "string",
                "title": "Vendor"
            },
            "mqtt_server": {
                "type": "string",
                "title": "MQTT Server",
                "default": "mqtt://127.0.0.1:1883"
            },
            "mqtt_base_topic": {
                "type": "string",
                "title": "MQTT Base Topic",
                "default": "zigbee2mqtt"
            },
            "sidecar_base_url": {
                "type": "string",
                "title": "Zigbee2MQTT Sidecar URL"
            }
        }
    },
    "uiSchema": {
        "friendly_name": {
            "placeholder": "living_room_motion"
        },
        "alias": {
            "placeholder": "Living Room Motion"
        },
        "ieee_address": {
            "placeholder": "0x00158d0000000000"
        },
        "mqtt_server": {
            "placeholder": "mqtt://127.0.0.1:1883"
        },
        "mqtt_base_topic": {
            "placeholder": "zigbee2mqtt"
        },
        "sidecar_base_url": {
            "placeholder": "http://127.0.0.1:8720"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "zigbee-device",
    "name": "Zigbee Device",
    "device_id": "zigbee-device",
    "entity_type": "zigbee_device",
    "capabilities": [
        "connected",
        "availability",
        "linkquality",
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
