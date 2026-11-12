from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from piphi_network_zigbee2mqtt.bridge_models import MqttSettings
from piphi_network_zigbee2mqtt.zigbee2mqtt_mqtt import Zigbee2MqttMqttClient


class FakeMqttModule:
    instances: list["FakeMqttClient"] = []

    class Client:
        def __init__(self, client_id: str) -> None:
            self.client_id = client_id
            self.on_connect = None
            self.on_subscribe = None
            self.on_message = None
            self.subscriptions: list[str] = []
            self.published: list[tuple[str, str]] = []
            self.username: str | None = None
            self.password: str | None = None
            FakeMqttModule.instances.append(self)

        def username_pw_set(self, username: str, password: str | None) -> None:
            self.username = username
            self.password = password

        def connect(self, host: str, port: int, keepalive: int) -> None:
            self.host = host
            self.port = port
            self.keepalive = keepalive
            self.on_connect(self, None, None, 0)

        def loop_start(self) -> None:
            pass

        def loop_stop(self) -> None:
            pass

        def disconnect(self) -> None:
            pass

        def subscribe(self, topic: str) -> None:
            self.subscriptions.append(topic)
            if topic.endswith("/bridge/devices"):
                payload = [
                    {
                        "friendly_name": "Kitchen Plug",
                        "ieee_address": "0x00158d00018255df",
                        "type": "Router",
                        "interview_state": "successful",
                        "supported": True,
                    }
                ]
                self.on_message(self, None, SimpleNamespace(payload=json.dumps(payload).encode("utf-8")))
            if self.on_subscribe:
                self.on_subscribe(self, None, 1, [0])

        def publish(self, topic: str, payload: str) -> None:
            self.published.append((topic, payload))
            request = json.loads(payload)
            if topic.endswith("/networkmap"):
                response = {
                    "status": "ok",
                    "data": {
                        "value": {
                            "nodes": [
                                {
                                    "ieeeAddr": "0x0000",
                                    "friendlyName": "Coordinator",
                                    "type": "Coordinator",
                                    "networkAddress": 0,
                                },
                                {
                                    "ieeeAddr": "0x1111",
                                    "friendlyName": "Hall router",
                                    "type": "Router",
                                    "networkAddress": 42,
                                    "manufacturerName": "Example",
                                    "modelID": "Router 1",
                                },
                            ],
                            "links": [
                                {
                                    "source": {"ieeeAddr": "0x0000"},
                                    "target": {"networkAddress": 42},
                                    "linkquality": 210,
                                    "depth": 1,
                                    "routes": [42],
                                }
                            ],
                        },
                        "type": "raw",
                        "routes": request["routes"],
                    },
                    "transaction": request["transaction"],
                }
            else:
                response = {
                    "status": "ok",
                    "data": {"time": request["time"]},
                    "transaction": request["transaction"],
                }
            self.on_message(self, None, SimpleNamespace(payload=json.dumps(response).encode("utf-8")))


FakeMqttClient = FakeMqttModule.Client


@pytest.mark.anyio
async def test_list_devices_reads_retained_bridge_devices_topic() -> None:
    FakeMqttModule.instances.clear()
    client = Zigbee2MqttMqttClient(
        mqtt=MqttSettings(server="mqtt://user:pass@broker.local:1884", base_topic="zigbee2mqtt"),
        mqtt_module=FakeMqttModule,
    )

    result = await client.list_devices()

    assert result.ok is True
    assert result.response_topic == "zigbee2mqtt/bridge/devices"
    assert result.request_topic is None
    assert result.devices[0].friendly_name == "Kitchen Plug"
    assert result.devices[0].interview_state == "successful"
    assert result.devices[0].import_eligible is True
    assert result.model_dump(mode="json")["server"] == "mqtt://broker.local:1884"
    fake_client = FakeMqttModule.instances[0]
    assert fake_client.host == "broker.local"
    assert fake_client.port == 1884
    assert fake_client.username == "user"
    assert fake_client.password == "pass"
    assert fake_client.subscriptions == ["zigbee2mqtt/bridge/devices"]


def test_device_import_eligibility_uses_current_interview_state() -> None:
    from piphi_network_zigbee2mqtt.bridge_models import Zigbee2MqttDevice

    interviewing = Zigbee2MqttDevice(
        friendly_name="Joining sensor",
        interview_state="interviewing",
        supported=True,
    )
    unsupported = Zigbee2MqttDevice(
        friendly_name="Unknown sensor",
        interview_state="successful",
        supported=False,
    )

    assert interviewing.import_eligible is False
    assert interviewing.import_blocked_reason == "interview_in_progress"
    assert unsupported.import_eligible is False
    assert unsupported.import_blocked_reason == "unsupported"


@pytest.mark.anyio
async def test_permit_join_uses_request_response_transaction() -> None:
    FakeMqttModule.instances.clear()
    client = Zigbee2MqttMqttClient(
        mqtt=MqttSettings(server="mqtt://broker.local:1883", base_topic="zigbee2mqtt"),
        mqtt_module=FakeMqttModule,
    )

    result = await client.permit_join(value=True, time=45, device="coordinator")

    assert result.ok is True
    assert result.request_topic == "zigbee2mqtt/bridge/request/permit_join"
    assert result.response_topic == "zigbee2mqtt/bridge/response/permit_join"
    assert result.transaction is not None
    fake_client = FakeMqttModule.instances[0]
    topic, payload = fake_client.published[0]
    decoded = json.loads(payload)
    assert topic == "zigbee2mqtt/bridge/request/permit_join"
    assert decoded["time"] == 45
    assert decoded["device"] == "coordinator"
    assert decoded["transaction"] == result.transaction


@pytest.mark.anyio
async def test_network_map_requests_raw_topology_and_normalizes_nodes_and_links() -> None:
    FakeMqttModule.instances.clear()
    client = Zigbee2MqttMqttClient(
        mqtt=MqttSettings(server="mqtt://broker.local:1883", base_topic="home/zigbee"),
        mqtt_module=FakeMqttModule,
    )

    result = await client.network_map(routes=True)

    assert result.ok is True
    assert result.routes_included is True
    assert [node.id for node in result.nodes] == ["0x0000", "0x1111"]
    assert result.nodes[1].manufacturer == "Example"
    assert result.links[0].source == "0x0000"
    assert result.links[0].target == "0x1111"
    assert result.links[0].link_quality == 210
    assert result.links[0].routes == [42]
    topic, payload = FakeMqttModule.instances[0].published[0]
    assert topic == "home/zigbee/bridge/request/networkmap"
    assert json.loads(payload)["type"] == "raw"
