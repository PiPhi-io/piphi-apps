from __future__ import annotations

from typing import Any

ENDPOINTS = {
    "health": "/health", "diagnostics": "/diagnostics",
    "entities": "/entities", "state": "/state", "config": "/config",
    "config_sync": "/config/sync", "deconfigure": "/deconfigure",
    "ui_config": "/ui-config", "events": "/events", "command": "/command",
    "camera_source": "/v1/cameras/{config_id}/source",
}
REQUIRED_ENDPOINTS = ["health", "entities", "command", "config", "ui_config"]
CAPABILITIES: dict[str, dict[str, Any]] = {
    "camera_stream": {
        "kind": "camera",
        "value_kind": "camera",
        "camera": {
            "contract_version": "camera.media.v1",
            "gateway_source_endpoint": "/v1/cameras/{config_id}/source",
            "refresh_seconds": 15,
        },
    },
    "refresh": {"kind": "action"},
}
COMMANDS: dict[str, dict[str, Any]] = {
    "refresh": {"description": "Refresh camera availability.", "timeout_ms": 5000}
}
CONFIG_SCHEMA: dict[str, Any] = {
    "schema": {
        "title": "RTSP camera setup", "type": "object", "required": ["source_url"],
        "properties": {
            "source_url": {
                "type": "string",
                "title": "RTSP camera URL",
                "description": (
                    "RTSP or RTSPS address supplied by your camera or NVR, without credentials."
                ),
            },
            "username": {
                "type": "string",
                "title": "Username",
                "description": (
                    "Optional. Use the camera's RTSP username, not your PiPhi account."
                ),
                "maxLength": 512,
            },
            "password": {
                "type": "string",
                "title": "Password",
                "description": "Optional. Enter the camera's RTSP password.",
                "format": "password",
                "writeOnly": True,
                "maxLength": 1024,
            },
            "alias": {"type": "string", "title": "Camera name", "maxLength": 120},
            "preferred_transport": {"type": "string", "title": "RTSP transport", "enum": ["tcp", "udp", "auto"], "default": "tcp"},
        },
    },
    "uiSchema": {
        "source_url": {
            "placeholder": "rtsp://camera.local:554/stream0",
        },
        "username": {"placeholder": "Camera username"},
        "password": {"ui:widget": "password", "placeholder": "Camera password"},
        "alias": {"placeholder": "Front door"},
    },
}
FALLBACK_ENTITY: dict[str, Any] = {
    "id": "camera", "name": "Camera", "device_id": "camera", "entity_type": "camera",
    "capabilities": ["camera_stream", "refresh"],
    "available_commands": [{"id": "refresh", "label": "Refresh", "kind": "action"}],
    "dashboard": {"allowed_widgets": ["camera", "camera-card", "io.piphi.webrtc.camera"], "default_widget": "camera"},
}
