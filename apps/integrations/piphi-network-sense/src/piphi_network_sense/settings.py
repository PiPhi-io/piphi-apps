from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-sense"
INTEGRATION_NAME = "Sense Energy"
INTEGRATION_VERSION = "0.1.2"
PROJECT_KIND = "integration"
PROJECT_PRESET = "cloud-polling-api"
PROJECT_DOMAIN = "cloud-api"
DEFAULT_PORT = 8090


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
