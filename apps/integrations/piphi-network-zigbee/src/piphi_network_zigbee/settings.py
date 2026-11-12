from __future__ import annotations

import os
from urllib.parse import urlparse

INTEGRATION_ID = "piphi-network-zigbee"
INTEGRATION_NAME = "PiPhi Network Zigbee"
INTEGRATION_VERSION = "0.1.10"
PROJECT_KIND = "integration"
PROJECT_PRESET = "protocol-bridge"
PROJECT_DOMAIN = "bridge"
DEFAULT_PORT = 8730


def _normalize_sidecar_base_url(value: str | None) -> str:
    token = str(value or "http://127.0.0.1:8720").strip().rstrip("/")
    parsed = urlparse(token if "://" in token else f"http://{token}")
    if parsed.scheme == "mqtt":
        return f"http://{parsed.netloc}{parsed.path}".rstrip("/")
    return token


DEFAULT_SIDECAR_BASE_URL = _normalize_sidecar_base_url(os.getenv("ZIGBEE2MQTT_SIDECAR_URL"))
DEFAULT_MQTT_SERVER = (
    os.getenv("MQTT_URL")
    or os.getenv("MQTT_SERVER")
    or "mqtt://127.0.0.1:1883"
).strip()
DEFAULT_MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "zigbee2mqtt").strip().strip("/") or "zigbee2mqtt"


def runtime_port() -> int:
    raw_port = os.getenv("PORT", str(DEFAULT_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PORT
