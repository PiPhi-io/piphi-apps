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
    "temperature_c": {
        "kind": "sensor",
        "unit": "C"
    },
    "refresh": {
        "kind": "action"
    },
    "api_rate_limit_remaining": {
        "kind": "sensor",
        "unit": "requests"
    },
    "api_latency_ms": {
        "kind": "sensor",
        "unit": "ms"
    },
    "humidity_percent": {
        "kind": "sensor",
        "unit": "%"
    },
    "precipitation_mm": {
        "kind": "sensor",
        "unit": "mm"
    },
    "precipitation_accumulated_mm": {
        "kind": "sensor",
        "unit": "mm"
    },
    "wind_speed_ms": {
        "kind": "sensor",
        "unit": "m/s"
    },
    "wind_gust_ms": {
        "kind": "sensor",
        "unit": "m/s"
    },
    "wind_direction_deg": {
        "kind": "sensor",
        "unit": "deg"
    },
    "pressure_hpa": {
        "kind": "sensor",
        "unit": "hPa"
    },
    "uv_index": {
        "kind": "sensor",
        "unit": "index"
    },
    "feels_like_c": {
        "kind": "sensor",
        "unit": "C"
    },
    "dew_point_c": {
        "kind": "sensor",
        "unit": "C"
    },
    "solar_irradiance_w_m2": {
        "kind": "sensor",
        "unit": "W/m2"
    },
    "qod_score": {
        "kind": "sensor",
        "unit": "score"
    },
    "sync_cloud": {
        "kind": "action"
    }
}

COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {
        "description": "Refresh the device state.",
        "timeout_ms": 5000
    },
    "sync_cloud": {
        "description": "Synchronize state from the vendor cloud.",
        "timeout_ms": 15000
    }
}

CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "PiPhi Network WeatherXM Setup",
        "type": "object",
        "required": [
            "station_id"
        ],
        "properties": {
            "station_id": {
                "type": "string",
                "title": "WeatherXM Station ID"
            },
            "alias": {
                "type": "string",
                "title": "Alias"
            },
            "base_url": {
                "type": "string",
                "title": "Base URL"
            },
            "api_token": {
                "type": "string",
                "title": "Access Token"
            },
            "username": {
                "type": "string",
                "title": "WeatherXM Email"
            },
            "password": {
                "type": "string",
                "title": "WeatherXM Password"
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll Interval Seconds",
                "minimum": 15
            }
        }
    },
    "uiSchema": {
        "station_id": {
            "placeholder": "12345"
        },
        "alias": {
            "placeholder": "Backyard WeatherXM"
        },
        "base_url": {
            "placeholder": "https://api.weatherxm.com/api/v1"
        },
        "api_token": {
            "placeholder": "Bearer token from WeatherXM auth"
        },
        "username": {
            "placeholder": "weatherxm@example.com"
        },
        "password": {
            "placeholder": "WeatherXM password",
            "ui:widget": "password"
        },
        "poll_interval_seconds": {
            "placeholder": "60"
        }
    }
}

FALLBACK_ENTITY: dict[str, Any] = {
    "id": "weatherxm-station",
    "name": "WeatherXM Station",
    "device_id": "weatherxm-station",
    "entity_type": "sensor",
    "capabilities": [
        "connected",
        "temperature_c",
        "refresh",
        "api_rate_limit_remaining",
        "api_latency_ms",
        "humidity_percent",
        "precipitation_mm",
        "precipitation_accumulated_mm",
        "wind_speed_ms",
        "wind_gust_ms",
        "wind_direction_deg",
        "pressure_hpa",
        "uv_index",
        "feels_like_c",
        "dew_point_c",
        "solar_irradiance_w_m2",
        "qod_score",
        "sync_cloud"
    ],
    "available_commands": [
        {
            "id": "refresh",
            "label": "Refresh",
            "kind": "action"
        },
        {
            "id": "sync_cloud",
            "label": "Sync Cloud",
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
