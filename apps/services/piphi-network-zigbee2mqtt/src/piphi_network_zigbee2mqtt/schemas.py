from __future__ import annotations

import os
from typing import Literal

from piphi_runtime_kit_python import RuntimeConfig
from pydantic import model_validator

from .stopped_coordinator_evidence import StoppedCoordinatorEvidence


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
    coordinator_stop_authority: Literal["local", "core_managed_helper"] = "local"
    stopped_coordinator_evidence: StoppedCoordinatorEvidence | None = None

    @model_validator(mode="after")
    def require_managed_stop_evidence(self) -> DeviceConfig:
        if (
            self.coordinator_stop_authority == "core_managed_helper"
            and self.stopped_coordinator_evidence is None
        ):
            raise ValueError("Core-managed config sync requires stopped-coordinator evidence.")
        return self
