from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-kia-hyundai-connect"
INTEGRATION_NAME = "Piphi Network Kia Hyundai Connect"
INTEGRATION_VERSION = "0.1.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "cloud-polling-api"
PROJECT_DOMAIN = "cloud-api"
DEFAULT_PORT = 4217


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
