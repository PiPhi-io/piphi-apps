from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


@dataclass
class SimulatedMessage:
    topic: str
    payload: bytes
    retain: bool = False


class DeterministicMqttBroker:
    """In-memory MQTT/Zigbee2MQTT transport for deterministic CI and demos."""

    def __init__(self) -> None:
        self.clients: list[DeterministicMqttClient] = []
        self.retained: dict[str, bytes] = {}
        self.published: list[SimulatedMessage] = []
        self.online = True

    def emit(self, topic: str, payload: Any, *, retain: bool = False) -> None:
        encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        message = SimulatedMessage(topic, encoded, retain)
        self.published.append(message)
        if retain:
            self.retained[topic] = encoded
        for client in list(self.clients):
            client._deliver(message)

    def disconnect_all(self, reason_code: int = 1) -> None:
        self.online = False
        for client in list(self.clients):
            if callable(client.on_disconnect):
                client.on_disconnect(client, None, None, reason_code, None)


class DeterministicMqttClient:
    def __init__(self, broker: DeterministicMqttBroker, *_args: Any, **_kwargs: Any) -> None:
        self.broker = broker
        self.subscriptions: set[str] = set()
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.on_subscribe = None
        self.credentials: tuple[str, str | None] | None = None

    def username_pw_set(self, user: str, password: str | None = None) -> None:
        self.credentials = (user, password)

    def tls_set(self, **_kwargs: Any) -> None:
        return None

    def reconnect_delay_set(self, **_kwargs: Any) -> None:
        return None

    def max_queued_messages_set(self, _value: int) -> None:
        return None

    def max_inflight_messages_set(self, _value: int) -> None:
        return None

    def connect(self, *_args: Any, **_kwargs: Any) -> int:
        if not self.broker.online:
            raise OSError("simulated broker offline")
        self.broker.clients.append(self)
        return 0

    connect_async = connect

    def loop_start(self) -> None:
        if callable(self.on_connect):
            self.on_connect(self, None, None, 0, None)

    def loop_stop(self) -> None:
        return None

    def disconnect(self) -> None:
        if self in self.broker.clients:
            self.broker.clients.remove(self)

    def subscribe(self, topic: str):
        self.subscriptions.add(topic)
        if callable(self.on_subscribe):
            self.on_subscribe(self, None, 1, [0], None)
        for retained_topic, payload in self.broker.retained.items():
            if _matches(topic, retained_topic):
                self._deliver(SimulatedMessage(retained_topic, payload, True))
        return (0, 1)

    def publish(self, topic: str, payload: str, **kwargs: Any):
        self.broker.emit(topic, payload.encode("utf-8"), retain=bool(kwargs.get("retain")))
        return SimpleNamespace(rc=0, wait_for_publish=lambda timeout=None: True, is_published=lambda: True)

    def _deliver(self, message: SimulatedMessage) -> None:
        if callable(self.on_message) and any(_matches(pattern, message.topic) for pattern in self.subscriptions):
            self.on_message(self, None, message)


class DeterministicMqttModule:
    CallbackAPIVersion = SimpleNamespace(VERSION2=2)

    def __init__(self, broker: DeterministicMqttBroker | None = None) -> None:
        self.broker = broker or DeterministicMqttBroker()

    def Client(self, *_args: Any, **_kwargs: Any) -> DeterministicMqttClient:
        return DeterministicMqttClient(self.broker)


def _matches(pattern: str, topic: str) -> bool:
    return pattern == topic or (pattern.endswith("/#") and topic.startswith(pattern[:-1]))
