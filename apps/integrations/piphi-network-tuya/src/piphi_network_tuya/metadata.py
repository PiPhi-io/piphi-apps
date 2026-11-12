from __future__ import annotations

from typing import Any

from .contract import (
    AIR_PURIFIER_FALLBACK_ENTITY,
    CAPABILITIES,
    CLIMATE_FALLBACK_ENTITY,
    COMMANDS,
    COVER_FALLBACK_ENTITY,
    ENDPOINTS,
    FAN_FALLBACK_ENTITY,
    HUMIDIFIER_FALLBACK_ENTITY,
    LIGHT_FALLBACK_ENTITY,
    PLUG_FALLBACK_ENTITY,
    REQUIRED_ENDPOINTS,
)
from .settings import (
    DEFAULT_RUNTIME_PORT,
    INTEGRATION_ID,
    INTEGRATION_NAME,
    INTEGRATION_VERSION,
    PROJECT_DOMAIN,
    PROJECT_PRESET,
)


def _connected_condition(label_prefix: str) -> dict[str, Any]:
    return {
        "id": "connected",
        "label": f"{label_prefix} is connected",
        "type": "boolean",
        "capability": "sensor.connected",
        "operators": ["eq", "neq"],
        "runtime": {
            "source": "state",
            "field": "connected",
            "operator": "eq",
        },
    }


def _power_state_condition(label_prefix: str) -> dict[str, Any]:
    return {
        "id": "power_state",
        "label": f"{label_prefix} power state",
        "type": "boolean",
        "capability": "sensor.power",
        "operators": ["eq", "neq"],
        "runtime": {
            "source": "state",
            "field": "power",
            "operator": "eq",
        },
    }


def build_manifest() -> dict[str, Any]:
    return {
        "$schema": "./schema/piphi-manifest.schema.json",
        "manifest_version": "1.0",
        "id": INTEGRATION_ID,
        "name": INTEGRATION_NAME,
        "version": INTEGRATION_VERSION,
        "description": "PiPhi integration runtime for Tuya LAN devices using TinyTuya.",
        "metadata": {
            "generator": "zed-agent",
            "preset": PROJECT_PRESET,
            "domain": PROJECT_DOMAIN,
            "vendor_library": "tinytuya",
        },
        "maintainer": {
            "name": "PiPhi Integrations Team",
            "website": "https://github.com/PiPhi-io",
        },
        "license": "MIT",
        "image": f"docker.io/piphinetwork/piphi-network-tuya:{INTEGRATION_VERSION}",
        "platforms": ["linux"],
        "runtime": {
            "linux": {
                "type": "container",
                "container": {
                    "image": f"docker.io/piphinetwork/piphi-network-tuya:{INTEGRATION_VERSION}",
                    "ports": [
                        {
                            "container": DEFAULT_RUNTIME_PORT,
                            "host": DEFAULT_RUNTIME_PORT,
                        }
                    ],
                    "environment": {
                        "PIPHI_RUNTIME_PORT": str(DEFAULT_RUNTIME_PORT),
                        "PIPHI_LOG_LEVEL": "INFO",
                        "PIPHI_TUYA_IO_TIMEOUT_SECONDS": "8",
                        "PIPHI_TUYA_DISCOVERY_TIMEOUT_SECONDS": "20",
                        "PIPHI_TUYA_STRICT_CONFIG_VALIDATION": "true",
                        "PIPHI_TUYA_POLL_JITTER_SECONDS": "2",
                        "PIPHI_TUYA_POLL_FAILURE_BACKOFF_SECONDS": "15",
                        "PIPHI_TUYA_POLL_ERROR_EVENT_COOLDOWN_SECONDS": "300",
                    },
                    "restart_policy": {
                        "name": "unless-stopped",
                        "maximum_retry_count": 0,
                    },
                },
                "discovery": {
                    "method": "direct",
                    "inputs": [
                        {
                            "name": "lan_scan",
                            "label": "Scan Local Network",
                            "type": "boolean",
                            "required": False,
                            "default": True,
                            "description": "Use TinyTuya LAN scanning to look for Tuya devices on the local network.",
                        },
                        {
                            "name": "scan_seconds",
                            "label": "LAN Scan Seconds",
                            "type": "number",
                            "required": False,
                            "default": 8,
                            "description": "How long the TinyTuya LAN scan should listen for local devices.",
                        },
                        {
                            "name": "force_scan",
                            "label": "Force Network Scan",
                            "type": "boolean",
                            "required": False,
                            "default": False,
                            "description": "Ask TinyTuya to actively force-scan for devices instead of relying only on broadcasts.",
                        },
                        {
                            "name": "host",
                            "label": "Device IP / Host",
                            "type": "text",
                            "required": False,
                            "placeholder": "192.168.1.50",
                            "description": "Optional host used for manual configuration when discovery is targeted or the device is already known.",
                        },
                        {
                            "name": "tuya_device_id",
                            "label": "Tuya Device ID",
                            "type": "text",
                            "required": False,
                            "placeholder": "bfxxxxxxxxxxxxxxxx",
                            "description": "Optional Tuya device id for manual discovery fallback or targeted setup.",
                        },
                        {
                            "name": "api_region",
                            "label": "Tuya Cloud Region",
                            "type": "text",
                            "required": False,
                            "placeholder": "us, eu, eu-w, in, cn",
                            "description": "Optional TinyTuya cloud region for cloud-backed discovery fallback.",
                        },
                        {
                            "name": "api_key",
                            "label": "Tuya Cloud API Key",
                            "type": "text",
                            "required": False,
                        },
                        {
                            "name": "api_secret",
                            "label": "Tuya Cloud API Secret",
                            "type": "password",
                            "secret": True,
                            "required": False,
                        },
                        {
                            "name": "api_device_id",
                            "label": "Tuya Cloud Seed Device ID",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
            }
        },
        "api": {
            "required": REQUIRED_ENDPOINTS,
            "base_url": f"http://127.0.0.1:{DEFAULT_RUNTIME_PORT}",
            "endpoints": {
                **ENDPOINTS,
                "manifest": "/manifest.json",
                "behaviors": "/behaviors.json",
                "manifest_static": "/manifest.static.json",
                "behaviors_static": "/behaviors.static.json",
            },
        },
        "config": {
            "source": "endpoint",
            "endpoint": "/ui-config",
            "required": True,
            "editable_fields": [
                "host",
                "tuya_device_id",
                "local_key",
                "alias",
                "device_type",
                "version",
                "switch",
                "fan_speed_dp",
                "fan_speed_max",
                "fan_oscillate_dp",
                "fan_mode_dp",
                "cover_control_dp",
                "cover_position_dp",
                "climate_target_temp_dp",
                "climate_current_temp_dp",
                "climate_mode_dp",
                "climate_temp_scale",
                "humidifier_target_humidity_dp",
                "humidifier_current_humidity_dp",
                "humidifier_mode_dp",
                "humidifier_humidity_scale",
                "purifier_speed_dp",
                "purifier_speed_max",
                "purifier_mode_dp",
                "purifier_aqi_dp",
                "purifier_aqi_scale",
                "poll_interval_seconds",
                "api_region",
                "api_key",
                "api_secret",
                "api_device_id",
            ],
            "runtime_fields": ["id", "config_id", "container_id", "device_id"],
            "identity_fields": ["tuya_device_id", "host"],
        },
        "identity": {
            "fields": ["tuya_device_id", "host"],
        },
        "capabilities": CAPABILITIES,
        "commands": COMMANDS,
        "entities": [
            PLUG_FALLBACK_ENTITY,
            LIGHT_FALLBACK_ENTITY,
            FAN_FALLBACK_ENTITY,
            COVER_FALLBACK_ENTITY,
            CLIMATE_FALLBACK_ENTITY,
            HUMIDIFIER_FALLBACK_ENTITY,
            AIR_PURIFIER_FALLBACK_ENTITY,
        ],
    }


def build_behaviors() -> dict[str, Any]:
    return {
        "devices": [
            {
                "id": "tuya_plug",
                "name": "Tuya plug",
                "description": "Local Tuya smart plug or outlet controlled over the LAN with TinyTuya.",
                "deviceClass": "outlet",
                "entityType": "switch",
                "capabilities": [
                    "connected",
                    "power",
                    "current_ma",
                    "power_w",
                    "voltage_v",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Plug"),
                    _power_state_condition("Plug"),
                    {
                        "id": "power_draw",
                        "label": "Power draw",
                        "type": "number",
                        "params": [
                            {
                                "name": "watts",
                                "label": "Watts",
                                "type": "number",
                                "required": True,
                                "unit": "W",
                            }
                        ],
                        "capability": "sensor.power_w",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "power_w",
                            "operator": ">",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_light",
                "name": "Tuya light",
                "description": "Local Tuya bulb or light strip with brightness, color temperature, and RGB controls.",
                "deviceClass": "light",
                "entityType": "light",
                "capabilities": [
                    "connected",
                    "power",
                    "mode",
                    "brightness_percent",
                    "color_temp_percent",
                    "color_value",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_brightness",
                    "set_color_temp",
                    "set_color_rgb",
                    "set_mode",
                ],
                "conditions": [
                    _connected_condition("Light"),
                    _power_state_condition("Light"),
                    {
                        "id": "brightness",
                        "label": "Brightness",
                        "type": "number",
                        "params": [
                            {
                                "name": "percent",
                                "label": "Brightness %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.brightness_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "brightness_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "mode_equals",
                        "label": "Light mode",
                        "type": "text",
                        "params": [
                            {
                                "name": "mode",
                                "label": "Mode",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.mode",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "mode",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {
                        "id": "set_brightness",
                        "label": "Set brightness",
                        "command": "set_brightness",
                    },
                    {
                        "id": "set_color_temp",
                        "label": "Set color temperature",
                        "command": "set_color_temp",
                    },
                    {
                        "id": "set_color_rgb",
                        "label": "Set RGB color",
                        "command": "set_color_rgb",
                    },
                    {
                        "id": "set_mode",
                        "label": "Set mode",
                        "command": "set_mode",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_fan",
                "name": "Tuya fan",
                "description": "Local Tuya fan with power, speed, oscillation, and optional mode controls.",
                "deviceClass": "fan",
                "entityType": "fan",
                "capabilities": [
                    "connected",
                    "power",
                    "fan_speed_percent",
                    "oscillating",
                    "mode",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_fan_speed",
                    "set_oscillate",
                    "set_mode",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Fan"),
                    _power_state_condition("Fan"),
                    {
                        "id": "fan_speed",
                        "label": "Fan speed",
                        "type": "number",
                        "params": [
                            {
                                "name": "percent",
                                "label": "Speed %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.fan_speed_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "fan_speed_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "oscillating",
                        "label": "Fan is oscillating",
                        "type": "boolean",
                        "capability": "sensor.oscillating",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "oscillating",
                            "operator": "eq",
                        },
                    },
                    {
                        "id": "mode_equals",
                        "label": "Fan mode",
                        "type": "text",
                        "params": [
                            {
                                "name": "mode",
                                "label": "Mode",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.mode",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "mode",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {
                        "id": "set_fan_speed",
                        "label": "Set fan speed",
                        "command": "set_fan_speed",
                    },
                    {
                        "id": "set_oscillate",
                        "label": "Set oscillation",
                        "command": "set_oscillate",
                    },
                    {
                        "id": "set_mode",
                        "label": "Set mode",
                        "command": "set_mode",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_cover",
                "name": "Tuya cover",
                "description": "Local Tuya curtain, blind, or shade with open, close, stop, and optional position controls.",
                "deviceClass": "cover",
                "entityType": "cover",
                "capabilities": [
                    "connected",
                    "position_percent",
                    "motion_state",
                    "refresh",
                    "open_cover",
                    "close_cover",
                    "stop_cover",
                    "set_cover_position",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Cover"),
                    {
                        "id": "position",
                        "label": "Cover position",
                        "type": "number",
                        "params": [
                            {
                                "name": "percent",
                                "label": "Position %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.position_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "position_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "motion_state",
                        "label": "Cover motion state",
                        "type": "text",
                        "params": [
                            {
                                "name": "motion_state",
                                "label": "Motion state",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.motion_state",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "motion_state",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "open_cover", "label": "Open", "command": "open_cover"},
                    {"id": "close_cover", "label": "Close", "command": "close_cover"},
                    {"id": "stop_cover", "label": "Stop", "command": "stop_cover"},
                    {
                        "id": "set_cover_position",
                        "label": "Set position",
                        "command": "set_cover_position",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_climate",
                "name": "Tuya climate",
                "description": "Local Tuya thermostat or climate device with target temperature, current temperature, power, and optional mode controls.",
                "deviceClass": "climate",
                "entityType": "climate",
                "capabilities": [
                    "connected",
                    "power",
                    "mode",
                    "temperature_c",
                    "target_temperature_c",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_temperature",
                    "set_mode",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Climate device"),
                    _power_state_condition("Climate"),
                    {
                        "id": "current_temperature",
                        "label": "Current temperature",
                        "type": "number",
                        "params": [
                            {
                                "name": "temperature_c",
                                "label": "Temperature °C",
                                "type": "number",
                                "required": True,
                                "unit": "C",
                            }
                        ],
                        "capability": "sensor.temperature_c",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "temperature_c",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "target_temperature",
                        "label": "Target temperature",
                        "type": "number",
                        "params": [
                            {
                                "name": "target_temperature_c",
                                "label": "Target temperature °C",
                                "type": "number",
                                "required": True,
                                "unit": "C",
                            }
                        ],
                        "capability": "sensor.target_temperature_c",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "target_temperature_c",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "mode_equals",
                        "label": "Climate mode",
                        "type": "text",
                        "params": [
                            {
                                "name": "mode",
                                "label": "Mode",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.mode",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "mode",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {
                        "id": "set_temperature",
                        "label": "Set temperature",
                        "command": "set_temperature",
                    },
                    {
                        "id": "set_mode",
                        "label": "Set mode",
                        "command": "set_mode",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_humidifier",
                "name": "Tuya humidifier",
                "description": "Local Tuya humidifier or diffuser with target humidity, current humidity, power, and optional mode controls.",
                "deviceClass": "humidifier",
                "entityType": "humidifier",
                "capabilities": [
                    "connected",
                    "power",
                    "mode",
                    "humidity_percent",
                    "target_humidity_percent",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_humidity",
                    "set_mode",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Humidifier"),
                    _power_state_condition("Humidifier"),
                    {
                        "id": "current_humidity",
                        "label": "Current humidity",
                        "type": "number",
                        "params": [
                            {
                                "name": "humidity_percent",
                                "label": "Humidity %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.humidity_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "humidity_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "target_humidity",
                        "label": "Target humidity",
                        "type": "number",
                        "params": [
                            {
                                "name": "target_humidity_percent",
                                "label": "Target humidity %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.target_humidity_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "target_humidity_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "mode_equals",
                        "label": "Humidifier mode",
                        "type": "text",
                        "params": [
                            {
                                "name": "mode",
                                "label": "Mode",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.mode",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "mode",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {
                        "id": "set_humidity",
                        "label": "Set humidity",
                        "command": "set_humidity",
                    },
                    {
                        "id": "set_mode",
                        "label": "Set mode",
                        "command": "set_mode",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
            {
                "id": "tuya_air_purifier",
                "name": "Tuya air purifier",
                "description": "Local Tuya air purifier with power, optional speed and mode controls, and optional air quality readings.",
                "deviceClass": "air_purifier",
                "entityType": "air_purifier",
                "capabilities": [
                    "connected",
                    "power",
                    "mode",
                    "fan_speed_percent",
                    "air_quality_index",
                    "refresh",
                    "turn_on",
                    "turn_off",
                    "set_fan_speed",
                    "set_mode",
                    "set_dp",
                ],
                "conditions": [
                    _connected_condition("Air purifier"),
                    _power_state_condition("Air purifier"),
                    {
                        "id": "fan_speed",
                        "label": "Purifier fan speed",
                        "type": "number",
                        "params": [
                            {
                                "name": "percent",
                                "label": "Speed %",
                                "type": "number",
                                "required": True,
                                "unit": "%",
                            }
                        ],
                        "capability": "sensor.fan_speed_percent",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "fan_speed_percent",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "air_quality",
                        "label": "Air quality index",
                        "type": "number",
                        "params": [
                            {
                                "name": "aqi",
                                "label": "AQI",
                                "type": "number",
                                "required": True,
                                "unit": "AQI",
                            }
                        ],
                        "capability": "sensor.air_quality_index",
                        "operators": [">", ">=", "<", "<=", "eq"],
                        "runtime": {
                            "source": "state",
                            "field": "air_quality_index",
                            "operator": ">",
                        },
                    },
                    {
                        "id": "mode_equals",
                        "label": "Purifier mode",
                        "type": "text",
                        "params": [
                            {
                                "name": "mode",
                                "label": "Mode",
                                "type": "text",
                                "required": True,
                            }
                        ],
                        "capability": "sensor.mode",
                        "operators": ["eq", "neq"],
                        "runtime": {
                            "source": "state",
                            "field": "mode",
                            "operator": "eq",
                        },
                    },
                ],
                "actions": [
                    {"id": "turn_on", "label": "Turn on", "command": "turn_on"},
                    {"id": "turn_off", "label": "Turn off", "command": "turn_off"},
                    {
                        "id": "set_fan_speed",
                        "label": "Set speed",
                        "command": "set_fan_speed",
                    },
                    {
                        "id": "set_mode",
                        "label": "Set mode",
                        "command": "set_mode",
                    },
                    {"id": "refresh", "label": "Refresh", "command": "refresh"},
                ],
            },
        ]
    }
