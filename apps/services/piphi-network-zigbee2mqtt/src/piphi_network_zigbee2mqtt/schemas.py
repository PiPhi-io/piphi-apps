from __future__ import annotations

from piphi_runtime_kit_python import RuntimeConfig


class DeviceConfig(RuntimeConfig):
    host: str = "127.0.0.1"
    alias: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    poll_interval_seconds: int | None = None
    service_name: str | None = None
    serial_port: str | None = None
    adapter: str | None = None
    mqtt_server: str = "mqtt://127.0.0.1:1883"
    mqtt_base_topic: str = "zigbee2mqtt"
    data_path: str = "/app/data"
