from __future__ import annotations

SERVICE_CAPABILITY = "camera.bridge.wyze.v1"

ENDPOINTS = {
    "health": "/health",
    "diagnostics": "/diagnostics",
    "contract": "/contract",
    "configure": "/v1/wyze-bridge/config",
    "deconfigure": "/v1/wyze-bridge/config",
    "status": "/v1/wyze-bridge/status",
    "cameras": "/v1/wyze-bridge/cameras",
}

REQUIRED_ENDPOINTS = ["health", "status", "configure", "cameras"]
