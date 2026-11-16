from __future__ import annotations

import json
import threading
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .bridge_models import MqttSettings
from .broker_health import parse_mqtt_endpoint
from .zigbee2mqtt_mqtt import (
    Zigbee2MqttMqttError,
    _configure_tls,
    _create_client,
    _load_paho_mqtt,
    _mqtt_credentials,
    _reason_code_failed,
)

MAX_GATEWAY_TOPICS = 256
MAX_GATEWAY_PAYLOAD_BYTES = 64 * 1024


@dataclass(frozen=True)
class CachedMqttMessage:
    sequence: int
    topic: str
    payload: Any


class ManagedMqttGateway:
    """Own the sidecar's only broker connection and expose bounded HTTP operations."""

    def __init__(self, mqtt_module: Any | None = None) -> None:
        self._mqtt_module = mqtt_module
        self._client: Any | None = None
        self._settings: MqttSettings | None = None
        self._messages: dict[str, CachedMqttMessage] = {}
        self._sequence = 0
        self._lock = threading.Lock()
        self.status = "stopped"
        self.message: str | None = None

    @property
    def base_topic(self) -> str | None:
        return self._settings.base_topic if self._settings else None

    def configure(self, settings: MqttSettings) -> None:
        if self._settings == settings and self._client is not None:
            return
        self.stop()
        self._settings = settings
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        client = _create_client(
            mqtt_module,
            client_id=f"piphi-z2m-gateway-{uuid.uuid4()}",
        )
        username, password = _mqtt_credentials(settings)
        if username:
            client.username_pw_set(username, password)
        _configure_tls(client, settings.server)

        def on_connect(client, _userdata, _flags, reason_code, _properties=None):
            if _reason_code_failed(reason_code):
                self.status = "error"
                self.message = f"mqtt_connect_failed:{reason_code}"
                return
            client.subscribe(f"{settings.base_topic}/#")
            self.status = "running"
            self.message = None

        def on_disconnect(_client, _userdata, _flags, reason_code, _properties=None):
            if self.status != "stopped":
                self.status = "disconnected"
                self.message = str(reason_code)

        def on_message(_client, _userdata, mqtt_message):
            payload = _decode_payload(bytes(mqtt_message.payload))
            if payload is None:
                return
            topic = str(mqtt_message.topic)
            if not _topic_is_within(topic, settings.base_topic):
                return
            with self._lock:
                self._sequence += 1
                self._messages[topic] = CachedMqttMessage(
                    sequence=self._sequence,
                    topic=topic,
                    payload=payload,
                )

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        reconnect_delay_set = getattr(client, "reconnect_delay_set", None)
        if callable(reconnect_delay_set):
            reconnect_delay_set(min_delay=1, max_delay=30)
        host, port = parse_mqtt_endpoint(settings.server)
        connect_async = getattr(client, "connect_async", None)
        try:
            if callable(connect_async):
                connect_async(host, port, keepalive=30)
            else:
                client.connect(host, port, keepalive=30)
            self.status = "starting"
            self.message = None
            client.loop_start()
            self._client = client
        except (OSError, RuntimeError, ValueError) as exc:
            self.status = "error"
            self.message = str(exc)
            with suppress(OSError, RuntimeError):
                client.loop_stop()

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            with suppress(OSError, RuntimeError):
                client.loop_stop()
            with suppress(OSError, RuntimeError):
                client.disconnect()
        self.status = "stopped"

    def messages(
        self,
        topics: list[str],
        *,
        after_sequence: int = 0,
    ) -> list[CachedMqttMessage]:
        settings = self._require_settings()
        resolved = [
            (topic.strip().strip("/"), _resolve_topic(topic, settings.base_topic))
            for topic in _bounded_topics(topics, settings.base_topic)
        ]
        with self._lock:
            return sorted(
                (
                    CachedMqttMessage(
                        sequence=self._messages[broker_topic].sequence,
                        topic=logical_topic,
                        payload=self._messages[broker_topic].payload,
                    )
                    for logical_topic, broker_topic in resolved
                    if broker_topic in self._messages
                    and self._messages[broker_topic].sequence > after_sequence
                ),
                key=lambda item: item.sequence,
            )

    def publish_json(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        settings = self._require_settings()
        logical_topic = _bounded_topics([topic], settings.base_topic)[0]
        broker_topic = _resolve_topic(logical_topic, settings.base_topic)
        encoded = json.dumps(payload, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_GATEWAY_PAYLOAD_BYTES:
            raise ValueError("MQTT command payload exceeds the sidecar limit.")
        if dry_run:
            return {
                "ok": True,
                "status": "planned",
                "topic": logical_topic,
                "payload": payload,
            }
        if self._client is None or self.status not in {"starting", "running"}:
            raise Zigbee2MqttMqttError("Managed MQTT gateway is unavailable.")
        result = self._client.publish(broker_topic, encoded, qos=1, retain=False)
        rc = getattr(result, "rc", 0)
        if int(rc or 0) != 0:
            raise Zigbee2MqttMqttError(f"MQTT publish failed with rc={rc}.")
        return {
            "ok": True,
            "status": "published",
            "topic": logical_topic,
            "payload": payload,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cached_topics = len(self._messages)
            sequence = self._sequence
        return {
            "status": self.status,
            "message": self.message,
            "base_topic": self.base_topic,
            "cached_topics": cached_topics,
            "sequence": sequence,
        }

    def _require_settings(self) -> MqttSettings:
        if self._settings is None:
            raise Zigbee2MqttMqttError("Managed MQTT gateway is not configured.")
        return self._settings


def _bounded_topics(topics: list[str], base_topic: str) -> list[str]:
    if not topics or len(topics) > MAX_GATEWAY_TOPICS:
        raise ValueError(f"topics must contain between 1 and {MAX_GATEWAY_TOPICS} entries.")
    normalized: list[str] = []
    for value in topics:
        topic = str(value or "").strip().strip("/")
        if not topic or "+" in topic or "#" in topic:
            raise ValueError("MQTT topic is outside the managed Zigbee namespace.")
        _resolve_topic(topic, base_topic)
        if topic not in normalized:
            normalized.append(topic)
    return normalized


def _topic_is_within(topic: str, base_topic: str) -> bool:
    return topic == base_topic or topic.startswith(f"{base_topic}/")


def _resolve_topic(topic: str, base_topic: str) -> str:
    normalized = str(topic or "").strip().strip("/")
    if _topic_is_within(normalized, base_topic):
        return normalized
    logical_base = base_topic.rsplit("/", 1)[-1]
    if not _topic_is_within(normalized, logical_base):
        raise ValueError("MQTT topic is outside the managed Zigbee namespace.")
    prefix = base_topic[: -len(logical_base)].rstrip("/")
    return f"{prefix}/{normalized}" if prefix else normalized


def _decode_payload(payload: bytes) -> Any | None:
    if not payload or len(payload) > MAX_GATEWAY_PAYLOAD_BYTES:
        return None
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


mqtt_gateway = ManagedMqttGateway()
