from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from piphi_network_zigbee2mqtt import state
from piphi_network_zigbee2mqtt.coordinator_claims import (
    CoordinatorClaimStore,
    stable_coordinator_identity,
)
from piphi_network_zigbee2mqtt.routes.config import _runtime_config_payloads
from piphi_network_zigbee2mqtt.schemas import DeviceConfig
from piphi_network_zigbee2mqtt.state import apply_config, sidecar_store

_EVIDENCE_SECRET = "managed-config-sync-test-secret-that-is-at-least-32-bytes"


def _managed_config_evidence(identity: str) -> dict[str, object]:
    issued_at = datetime.now(UTC)
    payload: dict[str, object] = {
        "protocol": "piphi.zigbee2mqtt.stopped-coordinator.v1",
        "operation": "config_sync",
        "coordinator_identity": identity,
        "generation": 42,
        "target_digest": "1" * 64,
        "helper_spec_digest": "2" * 64,
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued_at + timedelta(seconds=30)).isoformat().replace(
            "+00:00", "Z"
        ),
        "nonce": "stop.managed-config-sync",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["signature"] = hmac.new(
        _EVIDENCE_SECRET.encode(), canonical, hashlib.sha256
    ).hexdigest()
    return payload


class RuntimeConfigLike:
    def model_dump(self, *, mode: str):
        assert mode == "python"
        return {
            "id": "bridge-config",
            "config_id": "bridge-config",
            "container_id": "runtime-container",
            "serial_port": "/dev/ttyUSB0",
            "mqtt_server": "mqtt://user:pass@127.0.0.1:1883",
            "mqtt_base_topic": "zigbee2mqtt",
            "data_path": "/app/data",
        }


def test_runtime_config_payloads_normalizes_runtime_config_models() -> None:
    raw = {"id": "raw-config", "serial_port": "/dev/ttyUSB1"}

    payloads = _runtime_config_payloads([RuntimeConfigLike(), raw])

    assert payloads[0]["id"] == "bridge-config"
    assert payloads[0]["mqtt_server"] == "mqtt://user:pass@127.0.0.1:1883"
    assert payloads[1] is raw


@pytest.mark.anyio
async def test_apply_config_writes_zigbee2mqtt_configuration(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(state, "claim_store", CoordinatorClaimStore(tmp_path / "claims.json"))
    monkeypatch.setattr(
        state,
        "probe_coordinator",
        lambda _port: SimpleNamespace(available=True, message=None),
    )
    config = DeviceConfig(
        id="bridge-config",
        config_id="bridge-config",
        container_id="runtime-container",
        serial_port="/dev/ttyUSB0",
        coordinator_identity="usb:sonoff:serial-123",
        adapter="zstack",
        mqtt_server="mqtt://user:pass@127.0.0.1:1883",
        mqtt_base_topic="zigbee2mqtt",
        data_path=str(tmp_path),
    )

    await apply_config(config)

    config_path = tmp_path / "configuration.yaml"
    yaml = config_path.read_text(encoding="utf-8")
    assert 'server: "mqtt://127.0.0.1:1883"' in yaml
    assert 'user: "user"' in yaml
    assert 'password: "pass"' in yaml
    assert "user:pass@" not in yaml
    assert 'port: "/dev/ttyZigbee"' in yaml
    assert sidecar_store.config_path == str(config_path)
    assert sidecar_store.config_hash


@pytest.mark.anyio
async def test_apply_managed_config_uses_core_evidence_without_local_probe(
    tmp_path, monkeypatch
) -> None:
    identity = "serial-by-id:usb-sonoff-managed-config"
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setenv("PIPHI_COORDINATOR_EVIDENCE_KEY", _EVIDENCE_SECRET)
    monkeypatch.setenv(
        "PIPHI_COORDINATOR_EVIDENCE_LEDGER_PATH", str(tmp_path / "evidence.sqlite3")
    )
    monkeypatch.setattr(state, "claim_store", CoordinatorClaimStore(tmp_path / "claims.json"))
    monkeypatch.setattr(
        state,
        "probe_coordinator",
        lambda _port: (_ for _ in ()).throw(AssertionError("local probe must not run")),
    )
    sidecar_store.coordinator_identity = None
    sidecar_store.coordinator_owner_id = None
    config = DeviceConfig(
        id="managed-config",
        config_id="managed-config",
        container_id="runtime-container",
        serial_port="/dev/serial/by-id/usb-sonoff-managed-config",
        coordinator_identity=identity,
        adapter="zstack",
        mqtt_server="mqtt://127.0.0.1:1883",
        data_path=str(tmp_path),
        coordinator_stop_authority="core_managed_helper",
        stopped_coordinator_evidence=_managed_config_evidence(identity),
    )

    await apply_config(config)

    assert sidecar_store.current_config is not None
    assert sidecar_store.coordinator_identity == stable_coordinator_identity(identity)
    assert (tmp_path / "configuration.yaml").exists()

    with pytest.raises(Exception, match="already been used"):
        await apply_config(config)


@pytest.mark.anyio
async def test_apply_config_uses_managed_mqtt_identity_and_namespace(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(state, "claim_store", CoordinatorClaimStore(tmp_path / "claims.json"))
    monkeypatch.setattr(
        state,
        "probe_coordinator",
        lambda _port: SimpleNamespace(available=True, message=None),
    )
    configured = []
    monkeypatch.setattr(state.mqtt_gateway, "configure", configured.append)
    config = DeviceConfig(
        id="managed-bridge",
        config_id="managed-bridge",
        container_id="runtime-container",
        serial_port="/dev/ttyUSB0",
        coordinator_identity="usb:sonoff:managed-123",
        mqtt_server="mqtt://broker.internal:1883",
        mqtt_base_topic="zigbee2mqtt",
        mqtt_username="managed-user",
        mqtt_password="managed-password",
        mqtt_topic_prefix="piphi/managed-principal",
        data_path=str(tmp_path),
    )

    await apply_config(config)

    yaml = (tmp_path / "configuration.yaml").read_text(encoding="utf-8")
    assert 'base_topic: "piphi/managed-principal/zigbee2mqtt"' in yaml
    assert 'user: "managed-user"' in yaml
    assert 'password: "managed-password"' in yaml
    assert configured[0].base_topic == "piphi/managed-principal/zigbee2mqtt"
    assert "mqtt_password" not in state.registry.get("managed-bridge")["config"]
