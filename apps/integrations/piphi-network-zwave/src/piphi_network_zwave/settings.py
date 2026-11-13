from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-zwave"
INTEGRATION_NAME = "PiPhi Network Z-Wave"
INTEGRATION_VERSION = "0.3.0"
PROJECT_KIND = "integration"
PROJECT_PRESET = "protocol-bridge"
PROJECT_DOMAIN = "bridge"
DEFAULT_PORT = 4221
DEFAULT_SIDECAR_BASE_URL = os.getenv(
    "PIPHI_ZWAVE_SIDECAR_URL", "http://127.0.0.1:4211"
).strip().rstrip("/")
DEFAULT_EVENT_POLL_INTERVAL_SECONDS = 1.0


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
