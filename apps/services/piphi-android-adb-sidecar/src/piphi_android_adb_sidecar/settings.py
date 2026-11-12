from __future__ import annotations

import os

INTEGRATION_ID = "piphi-android-adb-sidecar"
INTEGRATION_NAME = "Piphi Android Adb Sidecar"
INTEGRATION_VERSION = "0.1.1"
PROJECT_KIND = "sidecar"
PROJECT_PRESET = "sidecar-worker"
PROJECT_DOMAIN = "sidecar-service"
DEFAULT_PORT = 4213


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
