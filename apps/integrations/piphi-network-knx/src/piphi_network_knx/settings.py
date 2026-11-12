from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-knx"
INTEGRATION_NAME = "Piphi Network Knx"
INTEGRATION_VERSION = "0.1.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "protocol-bridge"
PROJECT_DOMAIN = "bridge"
DEFAULT_PORT = 4223


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
