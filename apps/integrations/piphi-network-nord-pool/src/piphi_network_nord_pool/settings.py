from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-nord-pool"
INTEGRATION_NAME = "Piphi Network Nord Pool"
INTEGRATION_VERSION = "0.1.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "cloud-polling-api"
PROJECT_DOMAIN = "cloud-api"
DEFAULT_PORT = 4214


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
