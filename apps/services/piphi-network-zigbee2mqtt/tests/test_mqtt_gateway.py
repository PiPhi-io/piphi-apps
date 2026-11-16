from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from piphi_network_zigbee2mqtt.bridge_models import MqttSettings
from piphi_network_zigbee2mqtt.mqtt_gateway import ManagedMqttGateway


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
