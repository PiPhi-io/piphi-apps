from __future__ import annotations

import os

INTEGRATION_ID = "piphi-network-openepaperlink"
INTEGRATION_NAME = "OpenEPaperLink"
INTEGRATION_VERSION = "0.1.1"
PROJECT_KIND = "integration"
PROJECT_PRESET = "sensor-device"
PROJECT_DOMAIN = "local-device"
DEFAULT_PORT = 4219


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
