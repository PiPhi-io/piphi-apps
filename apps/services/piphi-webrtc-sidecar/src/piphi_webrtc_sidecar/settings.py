from __future__ import annotations

import os

INTEGRATION_ID = "piphi.service.webrtc-sidecar"
INTEGRATION_NAME = "PiPhi Camera Media Service"
INTEGRATION_VERSION = "0.3.4"
PROJECT_KIND = "platform_service"
PROJECT_PRESET = "platform-service"
PROJECT_DOMAIN = "camera-media"
DEFAULT_PORT = 8090


def runtime_port() -> int:
    raw_port = os.getenv("PORT")
    if raw_port is None:
        return DEFAULT_PORT
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port
