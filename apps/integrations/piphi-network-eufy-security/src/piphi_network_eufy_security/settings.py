from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-eufy-security"
INTEGRATION_NAME = "Piphi Network Eufy Security"
INTEGRATION_VERSION = "0.1.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "actuator-device"
PROJECT_DOMAIN = "local-device"
DEFAULT_PORT = 4210


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
