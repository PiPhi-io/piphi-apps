from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from piphi_network_zigbee2mqtt.bridge_models import MqttSettings
from piphi_network_zigbee2mqtt.mqtt_gateway import ManagedMqttGateway
from piphi_network_zigbee2mqtt.routes import bridge


class FakeMqttModule:
    instances: ClassVar[list[FakeClient]] = []

    class Client:
        def __init__(self, client_id: str) -> None:
            self.client_id = client_id
            self.on_connect = None
            self.on_disconnect = None
            self.on_message = None
            self.subscriptions: list[str] = []
            self.published: list[tuple[str, str, int, bool]] = []
            self.username: str | None = None
            self.password: str | None = None
            FakeMqttModule.instances.append(self)

        def username_pw_set(self, username: str, password: str | None) -> None:
            self.username = username
            self.password = password

        def reconnect_delay_set(self, **_kwargs) -> None:
            pass

        def connect_async(self, host: str, port: int, keepalive: int) -> None:
            self.host = host
            self.port = port
            self.keepalive = keepalive

        def loop_start(self) -> None:
            self.on_connect(self, None, None, 0)

        def loop_stop(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def subscribe(self, topic: str) -> None:
            self.subscriptions.append(topic)

        def publish(self, topic: str, payload: str, qos: int, retain: bool):
            self.published.append((topic, payload, qos, retain))
            return SimpleNamespace(rc=0)

        def emit(self, topic: str, payload: object) -> None:
            encoded = payload if isinstance(payload, str) else json.dumps(payload)
            self.on_message(
                self,
                None,
                SimpleNamespace(topic=topic, payload=encoded.encode("utf-8")),
            )


FakeClient = FakeMqttModule.Client


def test_gateway_owns_managed_namespace_and_credentials() -> None:
    FakeMqttModule.instances.clear()
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule)

    gateway.configure(
        MqttSettings(
            server="mqtt://broker.local:1883",
            user="managed-user",
            password="managed-password",
            base_topic="piphi/principal/zigbee2mqtt",
        )
    )
    client = FakeMqttModule.instances[0]
    client.emit("piphi/principal/zigbee2mqtt/kitchen", {"state": "ON"})

    messages = gateway.messages(["zigbee2mqtt/kitchen"])
    published = gateway.publish_json(
        "zigbee2mqtt/kitchen/set",
        {"state": "OFF"},
    )

    assert gateway.status == "running"
    assert client.username == "managed-user"
    assert client.password == "managed-password"
    assert client.subscriptions == ["piphi/principal/zigbee2mqtt/#"]
    assert messages[0].payload == {"state": "ON"}
    assert messages[0].topic == "zigbee2mqtt/kitchen"
    assert published["status"] == "published"
    assert published["topic"] == "zigbee2mqtt/kitchen/set"
    assert client.published == [
        (
            "piphi/principal/zigbee2mqtt/kitchen/set",
            '{"state":"OFF"}',
            1,
            False,
        )
    ]


def test_gateway_rejects_topics_outside_managed_namespace() -> None:
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule)
    gateway.configure(
        MqttSettings(
            server="mqtt://broker.local:1883",
            base_topic="piphi/principal/zigbee2mqtt",
        )
    )

    with pytest.raises(ValueError, match="outside"):
        gateway.publish_json("unmanaged/kitchen/set", {"state": "ON"})

    with pytest.raises(ValueError, match="outside"):
        gateway.messages(["piphi/other/zigbee2mqtt/kitchen"])


def test_gateway_journal_preserves_same_topic_transitions_for_each_cursor() -> None:
    FakeMqttModule.instances.clear()
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule, journal_capacity=8)
    gateway.configure(
        MqttSettings(server="mqtt://broker.local:1883", base_topic="zigbee2mqtt")
    )
    client = FakeMqttModule.instances[0]
    client.emit("zigbee2mqtt/kitchen", {"state": "ON"})
    client.emit("zigbee2mqtt/kitchen", {"state": "OFF"})
    client.emit("zigbee2mqtt/kitchen", {"state": "ON"})

    first_consumer = gateway.replay(["zigbee2mqtt/kitchen"], after_sequence=0)
    second_consumer = gateway.replay(["zigbee2mqtt/kitchen"], after_sequence=1)

    assert [message.payload["state"] for message in first_consumer.messages] == [
        "ON",
        "OFF",
        "ON",
    ]
    assert [message.sequence for message in second_consumer.messages] == [2, 3]
    assert first_consumer.cursor == 3
    assert first_consumer.gap is None


def test_gateway_journal_reports_an_explicit_overflow_gap() -> None:
    FakeMqttModule.instances.clear()
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule, journal_capacity=2)
    gateway.configure(
        MqttSettings(server="mqtt://broker.local:1883", base_topic="zigbee2mqtt")
    )
    client = FakeMqttModule.instances[0]
    client.emit("zigbee2mqtt/kitchen", {"state": "ON"})
    client.emit("zigbee2mqtt/kitchen", {"state": "OFF"})
    client.emit("zigbee2mqtt/kitchen", {"state": "ON"})

    replay = gateway.replay(["zigbee2mqtt/kitchen"], after_sequence=0)

    assert replay.gap == {"from_sequence": 1, "to_sequence": 1}
    assert [message.sequence for message in replay.messages] == [2, 3]
    assert gateway.snapshot()["journal_size"] == 2


def test_gateway_tracks_bridge_availability_and_broker_disconnect() -> None:
    FakeMqttModule.instances.clear()
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule)
    gateway.configure(
        MqttSettings(server="mqtt://broker.local:1883", base_topic="zigbee2mqtt")
    )
    client = FakeMqttModule.instances[0]

    assert gateway.snapshot()["availability"]["bridge"]["status"] == "unknown"
    client.emit("zigbee2mqtt/bridge/state", {"state": "online"})
    online = gateway.snapshot()["availability"]
    assert online["broker"]["status"] == "online"
    assert online["bridge"]["status"] == "online"
    assert online["coordinator"]["status"] == "online"
    assert online["bridge"]["updated_at"] is not None

    client.emit("zigbee2mqtt/bridge/health", {"healthy": False})
    assert gateway.snapshot()["availability"]["bridge"]["status"] == "offline"
    client.emit("zigbee2mqtt/bridge/info", {"coordinator": {"type": "zstack"}})
    assert gateway.snapshot()["availability"]["bridge"]["status"] == "online"
    assert gateway.snapshot()["availability"]["coordinator"]["status"] == "online"

    client.on_disconnect(client, None, None, 7)
    offline = gateway.snapshot()["availability"]
    assert offline["broker"]["status"] == "offline"
    assert offline["bridge"]["status"] == "offline"
    replay = gateway.replay(["zigbee2mqtt/bridge/state"], after_sequence=1)
    assert replay.messages[-1].payload["reason"] == "broker_disconnected"


@pytest.mark.anyio
async def test_mqtt_event_api_returns_cursor_and_gap(monkeypatch) -> None:
    FakeMqttModule.instances.clear()
    gateway = ManagedMqttGateway(mqtt_module=FakeMqttModule, journal_capacity=1)
    gateway.configure(
        MqttSettings(server="mqtt://broker.local:1883", base_topic="zigbee2mqtt")
    )
    client = FakeMqttModule.instances[0]
    client.emit("zigbee2mqtt/kitchen", {"state": "ON"})
    client.emit("zigbee2mqtt/kitchen", {"state": "OFF"})
    monkeypatch.setattr(bridge, "mqtt_gateway", gateway)

    response = await bridge.mqtt_messages(
        bridge.MqttMessagesRequest(
            topics=["zigbee2mqtt/kitchen"],
            after_sequence=0,
        )
    )

    assert response["sequence"] == 2
    assert response["gap"] == {"from_sequence": 1, "to_sequence": 1}
    assert response["messages"] == [
        {
            "sequence": 2,
            "topic": "zigbee2mqtt/kitchen",
            "payload": {"state": "OFF"},
        }
    ]
