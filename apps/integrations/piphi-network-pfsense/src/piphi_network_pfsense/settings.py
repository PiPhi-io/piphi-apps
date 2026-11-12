from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-pfsense"
INTEGRATION_NAME = "PiPhi Network pfSense"
INTEGRATION_VERSION = "0.1.8"
PROJECT_KIND = "integration"
PROJECT_PRESET = "cloud-polling-api"
PROJECT_DOMAIN = "local-device"
DEFAULT_PORT = 8090


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
