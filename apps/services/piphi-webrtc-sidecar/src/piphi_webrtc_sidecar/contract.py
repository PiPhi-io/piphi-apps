from __future__ import annotations

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "contract": "/contract",
    "camera_media_sessions": "/v1/camera-media/sessions",
    "camera_media_status": "/v1/camera-media/status",
}

REQUIRED_ENDPOINTS = ["health", "camera_media_status", "camera_media_sessions"]
CAMERA_MEDIA_CONTRACT_VERSION = "camera.media.v1"
