from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-midea-ac-lan"
INTEGRATION_NAME = "Piphi Network Midea Ac Lan"
INTEGRATION_VERSION = "0.3.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "actuator-device"
PROJECT_DOMAIN = "actuator"
DEFAULT_PORT = 4208


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
