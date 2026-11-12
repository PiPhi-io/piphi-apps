from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["ui_schema"])


@router.get("/ui-config")
@router.get("/ui")
async def get_ui_schema() -> dict:
    schema = {
        "title": "LG ThinQ Configuration",
        "description": "Configure an LG ThinQ device discovered from your ThinQ account.",
        "type": "object",
        "required": ["device_id", "device_type", "country_code"],
        "properties": {
            "simulation_mode": {
                "type": "boolean",
                "title": "Use simulator",
                "description": "Discover deterministic washer, refrigerator, and air-conditioner fixtures without an LG account.",
                "default": False,
            },
            "device_id": {
                "type": "string",
                "title": "Device ID",
                "description": "ThinQ device id selected from account discovery.",
            },
            "device_name": {
                "type": "string",
                "title": "Device Name",
                "description": "Optional discovered device name for display and traceability.",
                "default": "",
            },
            "device_type": {
                "type": "string",
                "title": "Device Type",
                "description": "ThinQ device type from discovery, such as DEVICE_AIR_CONDITIONER.",
            },
            "access_token": {
                "type": "string",
                "title": "Personal Access Token",
                "description": "LG ThinQ developer personal access token.",
            },
            "country_code": {
                "type": "string",
                "title": "Country Code",
                "description": "Two-letter ThinQ country code like US, CA, or KR.",
                "examples": ["US"],
            },
            "client_id": {
                "type": "string",
                "title": "Client ID (Optional)",
                "description": "Optional UUID-style ThinQ client id. PiPhi generates one automatically when omitted.",
                "default": "",
            },
            "alias": {
                "type": "string",
                "title": "Display Name (Optional)",
                "description": "Optional custom name used in dashboards.",
                "default": "",
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Polling Interval (Seconds)",
                "description": "How often PiPhi refreshes ThinQ device state.",
                "default": 60,
                "minimum": 15,
                "maximum": 900,
            },
            "push_events_enabled": {
                "type": "boolean",
                "title": "Enable near-real-time ThinQ events",
                "description": "Use LG's MQTT event service for faster updates while retaining polling as a fallback. Requires event and push scopes on the ThinQ token.",
                "default": False,
            },
        },
    }
    ui_schema = {
        "access_token": {
            "ui:options": {
                "text": {
                    "type": "password",
                    "autocomplete": "off",
                },
            },
        },
        "country_code": {
            "ui:options": {
                "text": {
                    "placeholder": "US",
                    "autocomplete": "country",
                },
            },
        },
        "client_id": {
            "ui:options": {
                "text": {
                    "placeholder": "Generated automatically when blank",
                    "autocomplete": "off",
                },
            },
        },
        "alias": {
            "ui:options": {
                "text": {
                    "placeholder": "Living Room AC",
                    "autocomplete": "off",
                },
            },
        },
    }
    return {"schema": schema, "uiSchema": ui_schema}
