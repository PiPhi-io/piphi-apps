from __future__ import annotations

import os

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str = "127.0.0.1"
    alias: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    poll_interval_seconds: int | None = None
    service_name: str | None = None
    serial_port: str | None = None
    coordinator_identity: str | None = None
    adapter: str | None = None
    mqtt_server: str = os.getenv("MQTT_URL") or os.getenv("MQTT_SERVER") or "mqtt://127.0.0.1:1883"
    mqtt_base_topic: str = "zigbee2mqtt"
    mqtt_username: str | None = os.getenv("MQTT_USERNAME")
    mqtt_password: str | None = os.getenv("MQTT_PASSWORD")
    mqtt_topic_prefix: str | None = os.getenv("MQTT_TOPIC_PREFIX")
    mqtt_credential_generation: int | None = None
    mqtt_binding: str | None = None
    data_path: str = "/app/data"
