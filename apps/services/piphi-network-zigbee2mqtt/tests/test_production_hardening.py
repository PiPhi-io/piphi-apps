from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from piphi_network_zigbee2mqtt.app import create_app
from piphi_network_zigbee2mqtt.bridge_models import (
    MqttSettings,
    PermitJoinResponse,
    SerialSettings,
    Zigbee2MqttBridgeConfig,
)
from piphi_network_zigbee2mqtt.commissioning import PermitJoinController
from piphi_network_zigbee2mqtt.config_renderer import render_zigbee2mqtt_config
from piphi_network_zigbee2mqtt.security import REDACTED, redact
from piphi_network_zigbee2mqtt.simulation import DeterministicMqttBroker, DeterministicMqttModule


@pytest.mark.anyio
async def test_production_auth_leaves_only_health_public(monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code in {200, 503}
        assert (await client.get("/entities")).status_code == 503
        monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN", "sidecar-secret")
        assert (await client.get("/entities")).status_code == 401
        response = await client.get(
            "/entities", headers={"authorization": "Bearer sidecar-secret"}
        )
        assert response.status_code == 200
        assert response.json()["entities"] == []


def test_recursive_redaction_covers_network_and_mqtt_secrets() -> None:
    result = redact(
        {
            "mqtt": {"password": "canary", "client_cert": "certificate"},
            "advanced": {"network_key": [1] * 16, "pan_id": 1234},
        }
    )
    assert result["mqtt"]["password"] == REDACTED
    assert result["advanced"]["network_key"] == REDACTED
    assert "canary" not in json.dumps(result)


def test_custom_ca_and_mtls_render_only_mounted_paths() -> None:
    settings = MqttSettings(
        server="mqtts://broker.local:8883",
        ca="/run/piphi/mqtt/ca.pem",
        cert="/run/piphi/mqtt/client.pem",
        key="/run/piphi/mqtt/client-key.pem",
    )
    rendered = render_zigbee2mqtt_config(
        Zigbee2MqttBridgeConfig(
            mqtt=settings,
            serial=SerialSettings(port="/dev/ttyUSB0", adapter="ember"),
        )
    )
    assert 'ca: "/run/piphi/mqtt/ca.pem"' in rendered.yaml
    assert 'reject_unauthorized: true' in rendered.yaml
    with pytest.raises(ValidationError):
        MqttSettings(server="mqtts://broker", cert="/cert.pem")
    with pytest.raises(ValidationError):
        MqttSettings(server="mqtts://broker", ca="relative-ca.pem")


@pytest.mark.anyio
async def test_permit_join_is_idempotent_and_explicitly_closed(tmp_path) -> None:
    calls: list[bool] = []

    async def call(*, value: bool, time: int, device: str | None, dry_run: bool):
        calls.append(value)
        return PermitJoinResponse(
            ok=True,
            status="ok",
            value=value,
            time=time,
            device=device,
            server="mqtt://broker",
            base_topic="zigbee2mqtt",
            request_topic="zigbee2mqtt/bridge/request/permit_join",
            response_topic="zigbee2mqtt/bridge/response/permit_join",
        )

    controller = PermitJoinController(tmp_path / "permit.json")
    mqtt = MqttSettings(server="mqtt://broker")
    first = await controller.execute(
        operation_id="commission-001",
        mqtt=mqtt,
        value=True,
        duration=30,
        device="coordinator",
        call=call,
    )
    replay = await controller.execute(
        operation_id="commission-001",
        mqtt=mqtt,
        value=True,
        duration=30,
        device="coordinator",
        call=call,
    )
    await controller.close(mqtt, call)
    assert first == replay
    assert calls == [True, False]
    assert not (tmp_path / "permit.json").exists()


def test_deterministic_transport_replays_retained_and_dependency_loss() -> None:
    broker = DeterministicMqttBroker()
    broker.emit("zigbee2mqtt/bridge/state", {"state": "online"}, retain=True)
    module = DeterministicMqttModule(broker)
    client = module.Client(client_id="test")
    received: list[bytes] = []
    disconnected: list[int] = []
    client.on_message = lambda _client, _userdata, message: received.append(message.payload)
    client.on_disconnect = lambda _client, _userdata, _flags, reason, _props: disconnected.append(reason)
    client.connect("broker", 1883)
    client.loop_start()
    client.subscribe("zigbee2mqtt/#")
    broker.disconnect_all()
    assert received == [b'{"state": "online"}']
    assert disconnected == [1]


def test_sidecar_catalog_excludes_entity_ownership() -> None:
    path = Path(__file__).resolve().parents[1] / "capability-catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in catalog["capabilities"] if item["id"] == "piphi_device_entities")
    assert row["status"] == "excluded"
