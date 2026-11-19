from __future__ import annotations

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "contract": "/contract",
    "camera_media_sessions": "/v1/camera-media/sessions",
    "camera_media_session_keepalive": "/v1/camera-media/sessions/{session_id}/keepalive",
    "camera_media_status": "/v1/camera-media/status",
    "analysis_media_issue": "/v1/analysis-media",
    "analysis_media": "/v1/analysis-media/{media_ref}",
}

REQUIRED_ENDPOINTS = [
    "health",
    "camera_media_status",
    "camera_media_sessions",
    "camera_media_session_keepalive",
    "analysis_media_issue",
    "analysis_media",
]
CAMERA_MEDIA_CONTRACT_VERSION = "camera.media.v1"
ANALYSIS_MEDIA_CONTRACT_VERSION = "camera.analysis-media.v1"
