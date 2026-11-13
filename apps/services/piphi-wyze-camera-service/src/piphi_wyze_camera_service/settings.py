from __future__ import annotations

import os

INTEGRATION_ID = "piphi.service.wyze-camera-bridge"
INTEGRATION_NAME = "PiPhi Wyze Camera Bridge"
INTEGRATION_VERSION = "0.1.3"
PROJECT_KIND = "platform_service"
PROJECT_PRESET = "platform-service"
PROJECT_DOMAIN = "camera-bridge"
DEFAULT_PORT = 8090
UPSTREAM_VERSION = "2.10.3"
UPSTREAM_CONTROL_URL = "http://127.0.0.1:5000"
INTERNAL_RTSP_PORT = 8554
DEFAULT_HOST_RTSP_PORT = 18554


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def host_rtsp_port() -> int:
    raw_port = os.getenv("PIPHI_WYZE_RTSP_HOST_PORT", str(DEFAULT_HOST_RTSP_PORT))
    try:
        port = int(raw_port)
    except ValueError:
        return DEFAULT_HOST_RTSP_PORT
    return port if 1 <= port <= 65535 else DEFAULT_HOST_RTSP_PORT
