from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-passive-ble-monitor"
INTEGRATION_NAME = "Piphi Network Passive Ble Monitor"
INTEGRATION_VERSION = "0.2.3"
PROJECT_KIND = "integration"
PROJECT_PRESET = "sensor-device"
PROJECT_DOMAIN = "sensor"
DEFAULT_PORT = 4204


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
