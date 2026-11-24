from fastapi import APIRouter

router = APIRouter(tags=["ui_schema"])


@router.get("/ui-config")
@router.get("/ui")
async def get_ui_schema() -> dict:
    schema = {
        "title": "TP-Link Kasa Configuration",
        "description": "Configure a TP-Link Kasa device for this integration.",
        "type": "object",
        "required": ["host"],
        "properties": {
            "host": {
                "type": "string",
                "title": "Device IP / Host",
                "description": "IPv4 address or hostname of the Kasa device (e.g. 192.168.1.50)",
                "examples": ["192.168.1.50"],
            },
            "alias": {
                "type": "string",
                "title": "Display Name (Optional)",
                "description": "Optional custom name used in dashboards.",
                "default": "",
            },
            "username": {
                "type": "string",
                "title": "Kasa Username (Optional)",
                "description": "Required only for devices that require authenticated local access.",
                "default": "",
            },
            "password": {
                "type": "string",
                "title": "Kasa Password (Optional)",
                "description": "Required only for devices that require authenticated local access.",
                "default": "",
            },
            "controls_enabled": {
                "type": "boolean",
                "title": "Enable qualified controls",
                "description": "Off by default. Requires an externally certified profile and command allow-list.",
                "default": False,
            },
            "certified_profile": {
                "type": "string",
                "title": "Certified profile ID",
                "description": "Profile supplied by a separate model/firmware qualification process.",
                "default": "",
            },
            "allowed_commands": {
                "type": "array",
                "title": "Allowed commands",
                "items": {"type": "string", "enum": ["turn_on", "turn_off", "set_brightness", "set_color_temperature", "set_hue_saturation"]},
                "maxItems": 8,
                "default": [],
            },
        },
    }
    ui_schema = {
        "host": {
            "ui:options": {
                "text": {
                    "placeholder": "192.168.1.50",
                    "autocomplete": "off",
                },
            },
        },
        "alias": {
            "ui:options": {
                "text": {
                    "placeholder": "Living Room Plug",
                    "autocomplete": "off",
                },
            },
        },
        "username": {
            "ui:options": {
                "text": {
                    "autocomplete": "username",
                },
            },
        },
        "password": {
            "ui:options": {
                "text": {
                    "type": "password",
                    "autocomplete": "current-password",
                },
            },
        },
    }
    return {"schema": schema, "uiSchema": ui_schema}
