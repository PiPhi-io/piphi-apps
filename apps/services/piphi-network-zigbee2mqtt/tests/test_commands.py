from __future__ import annotations

import httpx
import pytest

from piphi_network_zigbee2mqtt import state
from piphi_network_zigbee2mqtt.bridge_models import (
    MqttSettings,
    NetworkMapNode,
    NetworkMapResponse,
    SerialSettings,
    Zigbee2MqttBridgeConfig,
)
from piphi_network_zigbee2mqtt.main import app
from piphi_network_zigbee2mqtt.zigbee2mqtt_mqtt import Zigbee2MqttMqttClient


@pytest.mark.anyio
async def test_command_replays_key_without_repeating_runtime_effect() -> None:
    state.registry.recent_events.clear()
    headers = {"X-PiPhi-Idempotency-Key": "zigbee2mqtt-action-idempotency-1"}
    payload = {
        "command": "refresh",
        "config_id": "bridge-1",
        "device_id": "bridge-1",
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        first = await client.post("/command", json=payload, headers=headers)
        replay = await client.post("/command", json=payload, headers=headers)

    command_events = [
        event
        for event in state.registry.recent_events
        if event.get("event_type") == "runtime.command.received"
    ]
    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert len(command_events) == 1


@pytest.mark.anyio
async def test_refresh_network_map_command_updates_bound_runtime_state(monkeypatch) -> None:
    async def fake_network_map(self, *, routes=False, dry_run=False):
        return NetworkMapResponse(
            ok=True,
            status="ok",
            nodes=[NetworkMapNode(id="0x0000", friendly_name="Coordinator", type="Coordinator")],
            links=[],
            routes_included=routes,
            server=self.mqtt.server,
            base_topic=self.mqtt.base_topic,
            request_topic="zigbee2mqtt/bridge/request/networkmap",
            response_topic="zigbee2mqtt/bridge/response/networkmap",
        )

    monkeypatch.setattr(Zigbee2MqttMqttClient, "network_map", fake_network_map)
    state.sidecar_store.current_config = Zigbee2MqttBridgeConfig(
        mqtt=MqttSettings(server="mqtt://broker.local:1883"),
        serial=SerialSettings(port="/dev/ttyUSB0"),
    )
    state.registry.set(
        "bridge-map",
        {"config_id": "bridge-map", "device_id": "bridge-map", "config": {}},
    )
    payload = {
        "command": "refresh_network_map",
        "config_id": "bridge-map",
        "device_id": "bridge-map",
        "args": {"routes": False},
    }
    headers = {"X-PiPhi-Idempotency-Key": "zigbee2mqtt-network-map-command-1"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/command", json=payload, headers=headers)

    assert response.status_code == 200
    assert response.json()["topology"]["nodes"][0]["friendly_name"] == "Coordinator"
    snapshot = state.registry.state_snapshots["bridge-map"]
    assert snapshot["state"]["zigbee_network_topology"]["status"] == "ok"
