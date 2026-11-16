from __future__ import annotations

import httpx
import pytest

from piphi_network_zigbee2mqtt.bridge_models import (
    CoordinatorMigrationPlanRequest,
    CoordinatorProbeResponse,
    MqttSettings,
    SerialSettings,
    Zigbee2MqttBridgeConfig,
)
from piphi_network_zigbee2mqtt.coordinator_claims import CoordinatorClaimStore
from piphi_network_zigbee2mqtt.coordinator_migration import plan_coordinator_migration
from piphi_network_zigbee2mqtt.main import app
from piphi_network_zigbee2mqtt.network_backup import create_network_backup
from piphi_network_zigbee2mqtt.routes import bridge


def _available_probe(_port: str) -> CoordinatorProbeResponse:
    return CoordinatorProbeResponse(
        available=True,
        in_use=False,
        method="test",
        exclusive_verified=True,
    )


def _plan_request(tmp_path, backup, **updates) -> CoordinatorMigrationPlanRequest:
    values = {
        "data_path": str(tmp_path),
        "backup_path": backup.backup_path,
        "backup_sha256": backup.backup_sha256,
        "source_adapter_family": "ember",
        "target_adapter_family": "ember",
        "target_coordinator_identity": "usb:target:123",
        "target_coordinator_port": "/dev/serial/by-id/target-123",
        "target_adapter": "ember",
    }
    values.update(updates)
    return CoordinatorMigrationPlanRequest.model_validate(values)


def test_migration_plan_rejects_cross_family_without_evidence(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")

    with pytest.raises(ValueError, match="explicit compatibility evidence"):
        plan_coordinator_migration(
            _plan_request(tmp_path, backup, target_adapter_family="zstack"),
            probe=_available_probe,
        )


def test_migration_plan_requires_exclusive_target_probe(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")

    with pytest.raises(ValueError, match="exclusivity"):
        plan_coordinator_migration(
            _plan_request(tmp_path, backup),
            probe=lambda _port: CoordinatorProbeResponse(
                available=True,
                in_use=False,
                method="tcp_reachability",
                exclusive_verified=False,
            ),
        )


@pytest.mark.anyio
async def test_guided_same_family_migration_restores_and_retargets_config(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(bridge, "probe_coordinator", _available_probe)
    monkeypatch.setattr(bridge, "claim_store", CoordinatorClaimStore(tmp_path / "claims"))
    source_config = Zigbee2MqttBridgeConfig(
        mqtt=MqttSettings(server="mqtt://broker.local:1883"),
        serial=SerialSettings(port="/dev/serial/by-id/source-123", adapter="ember"),
        data_path=str(tmp_path),
    )
    bridge.sidecar_store.current_config = source_config
    bridge.sidecar_store.coordinator_identity = None
    bridge.sidecar_store.coordinator_owner_id = None
    (tmp_path / "configuration.yaml").write_text("source: true\n")
    (tmp_path / "coordinator_backup.json").write_text("{}")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")
    (tmp_path / "configuration.yaml").write_text("changed: true\n")
    request = _plan_request(tmp_path, backup)
    plan = plan_coordinator_migration(request, probe=_available_probe)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/coordinator-migration/apply",
            json={**request.model_dump(mode="json"), "plan_id": plan.plan_id, "confirm_migration": True},
        )

    assert response.status_code == 200, response.text
    assert response.json()["migrated"] is True
    assert bridge.sidecar_store.current_config is not None
    assert bridge.sidecar_store.current_config.serial.port == "/dev/serial/by-id/target-123"
    assert 'port: "/dev/ttyZigbee"' in (tmp_path / "configuration.yaml").read_text()


@pytest.mark.anyio
async def test_migration_requires_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    (tmp_path / "configuration.yaml").write_text("advanced: {}\n")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")
    request = _plan_request(tmp_path, backup)
    plan = plan_coordinator_migration(request, probe=_available_probe)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/coordinator-migration/apply",
            json={**request.model_dump(mode="json"), "plan_id": plan.plan_id},
        )

    assert response.status_code == 400
    assert "explicit confirmation" in response.json()["detail"]


@pytest.mark.anyio
async def test_migration_rolls_back_data_when_target_config_write_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(bridge, "probe_coordinator", _available_probe)
    monkeypatch.setattr(bridge, "claim_store", CoordinatorClaimStore(tmp_path / "claims"))
    source_config = Zigbee2MqttBridgeConfig(
        serial=SerialSettings(port="/dev/serial/by-id/source-123", adapter="ember"),
        data_path=str(tmp_path),
    )
    bridge.sidecar_store.current_config = source_config
    bridge.sidecar_store.coordinator_identity = None
    bridge.sidecar_store.coordinator_owner_id = None
    (tmp_path / "configuration.yaml").write_text("selected-backup: true\n")
    backup = create_network_backup(str(tmp_path), adapter_family="ember")
    (tmp_path / "configuration.yaml").write_text("current-before-migration: true\n")
    request = _plan_request(tmp_path, backup)
    plan = plan_coordinator_migration(request, probe=_available_probe)
    monkeypatch.setattr(
        bridge,
        "write_config_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/coordinator-migration/apply",
            json={**request.model_dump(mode="json"), "plan_id": plan.plan_id, "confirm_migration": True},
        )

    assert response.status_code == 409
    assert "rolled back" in response.json()["detail"]
    assert (tmp_path / "configuration.yaml").read_text() == "current-before-migration: true\n"
