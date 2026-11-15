from __future__ import annotations

import httpx
import pytest

from piphi_network_zigbee2mqtt.coordinator_claims import CoordinatorClaimStore
from piphi_network_zigbee2mqtt.main import app
from piphi_network_zigbee2mqtt.routes import bridge


@pytest.mark.anyio
async def test_v1_routes_require_valid_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ENV", raising=False)
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN", "expected-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        denied = await client.get("/v1/snapshot")
        accepted = await client.get(
            "/v1/snapshot",
            headers={"Authorization": "Bearer expected-token"},
        )

    assert denied.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.anyio
async def test_v1_routes_fail_closed_without_production_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_ZIGBEE2MQTT_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/v1/snapshot")

    assert response.status_code == 503


@pytest.mark.anyio
async def test_bridge_routes_render_and_snapshot(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ZIGBEE2MQTT_ALLOWED_DATA_ROOTS", str(tmp_path))
    monkeypatch.setattr(bridge, "claim_store", CoordinatorClaimStore(tmp_path / "claims.json"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        render_response = await client.post(
            "/v1/config/render",
            json={
                "config": {
                    "mqtt": {"server": "mqtt://127.0.0.1:1883", "base_topic": "zigbee2mqtt"},
                    "serial": {"port": "COM4", "adapter": "zstack"},
                    "runtime": "native",
                    "data_path": "C:/PiPhi/zigbee2mqtt",
                },
                "config_path": "C:/PiPhi/zigbee2mqtt/configuration.yaml",
            },
        )
        snapshot_response = await client.get("/v1/snapshot")
        supervisor_response = await client.post(
            "/v1/supervisor/start",
            json={
                "mode": "docker",
                "dry_run": True,
                "docker": {
                    "host_data_path": "/var/lib/piphi/zigbee2mqtt",
                    "device_path": "/dev/ttyUSB0",
                },
            },
        )
        logs_response = await client.post(
            "/v1/supervisor/logs",
            json={
                "mode": "pm2",
                "dry_run": True,
                "tail": 25,
                "pm2": {
                    "process_name": "piphi-zigbee2mqtt",
                    "working_dir": "/opt/zigbee2mqtt",
                },
            },
        )
        mqtt_response = await client.post(
            "/v1/mqtt/check",
            json={"server": "mqtt://broker.local:1883", "dry_run": True},
        )
        prerequisites_response = await client.post(
            "/v1/prerequisites",
            json={"mode": "docker", "dry_run": True},
        )
        devices_response = await client.post(
            "/v1/devices",
            json={
                "dry_run": True,
                "server": "mqtt://127.0.0.1:1883",
                "base_topic": "zigbee2mqtt",
            },
        )
        network_map_response = await client.post(
            "/v1/network-map",
            json={
                "dry_run": True,
                "routes": False,
                "server": "mqtt://127.0.0.1:1883",
                "base_topic": "zigbee2mqtt",
            },
        )
        permit_join_response = await client.post(
            "/v1/permit-join",
            json={
                "dry_run": True,
                "time": 30,
                "device": "coordinator",
                "server": "mqtt://127.0.0.1:1883",
                "base_topic": "zigbee2mqtt",
            },
        )
        apply_response = await client.post(
            "/v1/apply",
            json={
                "config_path": str(tmp_path / "configuration.yaml"),
                "restart_policy": "never",
                "coordinator_identity": "usb:sonoff-zbdongle-e:1234",
                "config": {
                    "mqtt": {"server": "mqtt://127.0.0.1:1883", "base_topic": "zigbee2mqtt"},
                    "serial": {"port": "/dev/ttyUSB0", "adapter": "ember"},
                    "runtime": "docker",
                    "data_path": str(tmp_path),
                },
                "mqtt_check": {"server": "mqtt://127.0.0.1:1883", "dry_run": True},
            },
        )
        network_change = {
            "config_path": str(tmp_path / "configuration.yaml"),
            "restart_policy": "never",
            "coordinator_identity": "usb:sonoff-zbdongle-e:1234",
            "config": {
                "mqtt": {"server": "mqtt://127.0.0.1:1883", "base_topic": "zigbee2mqtt"},
                "serial": {"port": "/dev/ttyUSB0", "adapter": "ember"},
                "runtime": "docker",
                "data_path": str(tmp_path),
                "advanced": {"network_key": list(range(16))},
            },
            "mqtt_check": None,
        }
        rejected_change_response = await client.post("/v1/apply", json=network_change)
        backup_response = await client.post("/v1/network-backup", json={"data_path": str(tmp_path)})
        backup = backup_response.json()
        accepted_change_response = await client.post(
            "/v1/apply",
            json=network_change
            | {
                "backup_path": backup["backup_path"],
                "backup_sha256": backup["backup_sha256"],
            },
        )
        monkeypatch.setattr(bridge, "claim_owner_id", lambda: "another-runtime")
        conflicting_owner_response = await client.post(
            "/v1/apply",
            json=network_change
            | {
                "backup_path": backup["backup_path"],
                "backup_sha256": backup["backup_sha256"],
            },
        )
        stop_response = await client.post(
            "/v1/supervisor/stop",
            json={
                "mode": "docker",
                "dry_run": True,
                "docker": {"host_data_path": "/var/lib/piphi/zigbee2mqtt"},
            },
        )
        new_owner_response = await client.post(
            "/v1/apply",
            json=network_change,
        )
        final_snapshot_response = await client.get("/v1/snapshot")

    assert render_response.status_code == 200
    rendered = render_response.json()
    assert 'port: "COM4"' in rendered["yaml"]
    assert rendered["runtime"] == "native"

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["configured"] is False
    assert snapshot["adapter_path"] is None

    assert supervisor_response.status_code == 200
    supervisor = supervisor_response.json()
    assert supervisor["ok"] is True
    assert supervisor["status"] == "planned"
    assert supervisor["commands"][1][0:3] == ["docker", "run", "-d"]

    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert logs["commands"][0] == ["pm2", "logs", "piphi-zigbee2mqtt", "--lines", "25", "--nostream"]

    assert mqtt_response.status_code == 200
    mqtt_check = mqtt_response.json()
    assert mqtt_check["ok"] is True
    assert mqtt_check["host"] == "broker.local"
    assert mqtt_check["port"] == 1883

    assert prerequisites_response.status_code == 200
    prerequisites = prerequisites_response.json()
    assert prerequisites["ok"] is True
    assert prerequisites["checks"][0]["name"] == "docker_available"

    assert devices_response.status_code == 200
    devices = devices_response.json()
    assert devices["ok"] is True
    assert devices["status"] == "planned"
    assert devices["response_topic"] == "zigbee2mqtt/bridge/devices"

    assert permit_join_response.status_code == 200
    permit_join = permit_join_response.json()
    assert permit_join["ok"] is True
    assert permit_join["status"] == "planned"
    assert permit_join["time"] == 30
    assert permit_join["device"] == "coordinator"
    assert permit_join["request_topic"] == "zigbee2mqtt/bridge/request/permit_join"

    assert network_map_response.status_code == 200
    network_map = network_map_response.json()
    assert network_map["ok"] is True
    assert network_map["status"] == "planned"
    assert network_map["request_topic"] == "zigbee2mqtt/bridge/request/networkmap"
    assert network_map["routes_included"] is False

    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["ok"] is True
    assert applied["restart_required"] is False
    assert applied["write"]["config_hash"].startswith("sha256:")
    assert rejected_change_response.status_code == 409
    assert backup_response.status_code == 200
    assert accepted_change_response.status_code == 200
    assert 'network_key: "[redacted]"' in accepted_change_response.json()["rendered"]["yaml"]
    assert "- 15" not in accepted_change_response.json()["rendered"]["yaml"]
    assert conflicting_owner_response.status_code == 409
    assert stop_response.status_code == 200
    assert new_owner_response.status_code == 200

    assert final_snapshot_response.status_code == 200
    final_snapshot = final_snapshot_response.json()
    assert final_snapshot["coordinator_claimed"] is True
    assert final_snapshot["devices"]["status"] == "planned"
    assert final_snapshot["network_map"]["status"] == "planned"
    assert final_snapshot["permit_join"]["status"] == "planned"
