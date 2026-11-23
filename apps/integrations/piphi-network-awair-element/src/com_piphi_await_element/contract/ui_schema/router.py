from fastapi import APIRouter

router = APIRouter(tags=['ui_schema'])

@router.get('/ui-config')
@router.get('/ui')
async def get_ui_schema():
    schema = {
        "title": "Awair Element API Configuration",
        "description":
            "Configuration for Awair Element Local  integration.",
        "type": "object",
        "required": ["device_ip", "device_identity"],
        "properties": {
            "device_ip": {
                "type": "string",
                "title": "Device IP Address",
                "description":
                    "IPv4 address of the Awair Element on your LAN (e.g., 192.168.1.100). Endpoint: http://{device_ip}/air-data/latest",
                "pattern":
                    "^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$",
                "examples": ["192.168.1.100"],
                "errorMessage": "Please provide a valid IPv4 address",
            },
            "device_identity": {
                "type": "string",
                "title": "Awair hardware identity",
                "description": "Stable identity reported by verified Awair mDNS discovery (for example AWAIR-ELEM-1450C8).",
                "minLength": 3,
                "maxLength": 128,
            },
            "device_mac": {
                "type": "string",
                "title": "Device MAC Address (Optional)",
                "description":
                    "MAC for whitelisting or discovery (12-digit hex starting with '70', e.g., 70:88:6B:00:00:00). Found on device back.",
                "pattern":
                    "^70:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}$",
                "examples": ["70:88:6B:00:00:00"],
                "errorMessage": "Please enter a valid mac address",
            },
            "poll_interval_seconds": {
                "type": "integer",
                "title": "Poll interval (seconds)",
                "minimum": 10,
                "maximum": 3600,
                "default": 30,
            },
        },
    }

    return {"schema": schema}
