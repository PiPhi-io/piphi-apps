from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-washdata"
INTEGRATION_NAME = "Piphi Network Washdata"
INTEGRATION_VERSION = "0.1.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "sensor-device"
PROJECT_DOMAIN = "sensor"
DEFAULT_PORT = 4211


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
