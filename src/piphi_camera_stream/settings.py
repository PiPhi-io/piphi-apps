from __future__ import annotations

import os

INTEGRATION_ID = "piphi-camera-stream"
INTEGRATION_NAME = "Piphi Camera Stream"
INTEGRATION_VERSION = "0.1.5"
PROJECT_KIND = "integration"
PROJECT_PRESET = "protocol-bridge"
PROJECT_DOMAIN = "local-device"
DEFAULT_PORT = 8090


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
