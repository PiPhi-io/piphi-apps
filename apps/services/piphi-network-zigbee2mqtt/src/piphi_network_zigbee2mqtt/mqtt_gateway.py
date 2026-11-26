from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
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
DEFAULT_GATEWAY_JOURNAL_CAPACITY = 4096


@dataclass(frozen=True)
class CachedMqttMessage:
    sequence: int
    topic: str
    payload: Any


@dataclass(frozen=True)
class MqttJournalReplay:
    messages: list[CachedMqttMessage]
    cursor: int
    gap: dict[str, int] | None
    oldest_sequence: int | None


class ManagedMqttGateway:
    """Own the sidecar's only broker connection and expose bounded HTTP operations."""

    def __init__(
        self,
        mqtt_module: Any | None = None,
        *,
        journal_capacity: int = DEFAULT_GATEWAY_JOURNAL_CAPACITY,
    ) -> None:
        if journal_capacity < 1:
            raise ValueError("journal_capacity must be positive")
        self._mqtt_module = mqtt_module
        self._client: Any | None = None
        self._settings: MqttSettings | None = None
        self._journal: deque[CachedMqttMessage] = deque(maxlen=journal_capacity)
        self._journal_capacity = journal_capacity
        self._sequence = 0
        self._lock = threading.Lock()
        self.status = "stopped"
        self.message: str | None = None
        self._availability = {
            "broker": {"status": "unknown", "updated_at": None},
            "bridge": {"status": "unknown", "updated_at": None},
            "coordinator": {"status": "unknown", "updated_at": None},
        }

    @property
    def base_topic(self) -> str | None:
        return self._settings.base_topic if self._settings else None

    def configure(self, settings: MqttSettings) -> None:
        if self._settings == settings and self._client is not None:
            return
        self.stop()
        self._settings = settings
        self._reset_availability()
        mqtt_module = self._mqtt_module or _load_paho_mqtt()
        client = _create_client(
            mqtt_module,
            client_id=f"piphi-z2m-gateway-{uuid.uuid4()}",
        )
        username, password = _mqtt_credentials(settings)
        if username:
            client.username_pw_set(username, password)
        _configure_tls(client, settings)
        max_queued_messages_set = getattr(client, "max_queued_messages_set", None)
        if callable(max_queued_messages_set):
            max_queued_messages_set(256)
        max_inflight_messages_set = getattr(client, "max_inflight_messages_set", None)
        if callable(max_inflight_messages_set):
            max_inflight_messages_set(20)

        def on_connect(client, _userdata, _flags, reason_code, _properties=None):
            if _reason_code_failed(reason_code):
                self.status = "error"
                self.message = f"mqtt_connect_failed:{reason_code}"
                self._set_availability("broker", "offline")
                return
            client.subscribe(f"{settings.base_topic}/#")
            self.status = "running"
            self.message = None
            self._set_availability("broker", "online")

        def on_disconnect(_client, _userdata, _flags, reason_code, _properties=None):
            if self.status != "stopped":
                self.status = "disconnected"
                self.message = str(reason_code)
                self._set_availability("broker", "offline")
                self._set_availability("bridge", "offline")
                self._set_availability("coordinator", "offline")
                self._append_message(
                    f"{settings.base_topic}/bridge/state",
                    {
                        "state": "offline",
                        "reason": "broker_disconnected",
                        "observed_at": _now(),
                    },
                )

        def on_message(_client, _userdata, mqtt_message):
            payload = _decode_payload(bytes(mqtt_message.payload))
            if payload is None:
                return
            topic = str(mqtt_message.topic)
            if not _topic_is_within(topic, settings.base_topic):
                return
            self._append_message(topic, payload)
            self._observe_bridge_message(topic, payload, settings.base_topic)

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
        self.status = "stopped"
        if client is not None:
            with suppress(OSError, RuntimeError):
                client.loop_stop()
            with suppress(OSError, RuntimeError):
                client.disconnect()
            self._set_availability("broker", "offline")
            self._set_availability("bridge", "offline")
            self._set_availability("coordinator", "offline")

    def messages(
        self,
        topics: list[str],
        *,
        after_sequence: int = 0,
    ) -> list[CachedMqttMessage]:
        return self.replay(topics, after_sequence=after_sequence).messages

    def replay(
        self,
        topics: list[str],
        *,
        after_sequence: int = 0,
    ) -> MqttJournalReplay:
        settings = self._require_settings()
        resolved = [
            (topic.strip().strip("/"), _resolve_topic(topic, settings.base_topic))
            for topic in _bounded_topics(topics, settings.base_topic)
        ]
        topic_names = {broker: logical for logical, broker in resolved}
        with self._lock:
            oldest_sequence = self._journal[0].sequence if self._journal else None
            gap = None
            if oldest_sequence is not None and after_sequence < oldest_sequence - 1:
                gap = {
                    "from_sequence": after_sequence + 1,
                    "to_sequence": oldest_sequence - 1,
                }
            messages = [
                CachedMqttMessage(
                    sequence=message.sequence,
                    topic=topic_names[message.topic],
                    payload=message.payload,
                )
                for message in self._journal
                if message.sequence > after_sequence and message.topic in topic_names
            ]
            return MqttJournalReplay(
                messages=messages,
                cursor=self._sequence,
                gap=gap,
                oldest_sequence=oldest_sequence,
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
            cached_topics = len({message.topic for message in self._journal})
            journal_size = len(self._journal)
            sequence = self._sequence
            availability = {
                component: dict(value)
                for component, value in self._availability.items()
            }
        return {
            "status": self.status,
            "message": self.message,
            "base_topic": self.base_topic,
            "cached_topics": cached_topics,
            "journal_size": journal_size,
            "journal_capacity": self._journal_capacity,
            "sequence": sequence,
            "availability": availability,
        }

    def _append_message(self, topic: str, payload: Any) -> None:
        with self._lock:
            self._sequence += 1
            self._journal.append(
                CachedMqttMessage(
                    sequence=self._sequence,
                    topic=topic,
                    payload=payload,
                )
            )

    def _set_availability(self, component: str, status: str) -> None:
        with self._lock:
            current = self._availability[component]
            if current["status"] == status:
                return
            current["status"] = status
            current["updated_at"] = _now()

    def _reset_availability(self) -> None:
        with self._lock:
            for current in self._availability.values():
                current["status"] = "unknown"
                current["updated_at"] = _now()

    def _observe_bridge_message(self, topic: str, payload: Any, base_topic: str) -> None:
        if topic == f"{base_topic}/bridge/state":
            value = payload.get("state") if isinstance(payload, dict) else payload
            status = _availability_status(value)
            if status:
                self._set_availability("bridge", status)
                self._set_availability("coordinator", status)
            return
        if topic == f"{base_topic}/bridge/info" and isinstance(payload, dict):
            self._set_availability("bridge", "online")
            if payload.get("coordinator") or payload.get("coordinator_meta"):
                self._set_availability("coordinator", "online")
            return
        if topic == f"{base_topic}/bridge/health" and isinstance(payload, dict):
            healthy = payload.get("healthy", payload.get("status"))
            status = _availability_status(healthy)
            if status:
                self._set_availability("bridge", status)

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


def _availability_status(value: Any) -> str | None:
    if isinstance(value, bool):
        return "online" if value else "offline"
    token = str(value or "").strip().lower()
    if token in {"online", "ok", "healthy", "true", "1"}:
        return "online"
    if token in {"offline", "error", "unhealthy", "false", "0"}:
        return "offline"
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


mqtt_gateway = ManagedMqttGateway()
