from __future__ import annotations

import httpx
import pytest

from piphi_network_zigbee2mqtt.main import app


@pytest.mark.anyio
async def test_bridge_routes_render_and_snapshot() -> None:
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
            json={"dry_run": True},
        )
        network_map_response = await client.post(
            "/v1/network-map",
            json={"dry_run": True, "routes": False},
        )
        permit_join_response = await client.post(
            "/v1/permit-join",
            json={"dry_run": True, "time": 30, "device": "coordinator"},
        )
        apply_response = await client.post(
            "/v1/apply",
            json={
                "config_path": "/tmp/piphi-zigbee2mqtt-test-configuration.yaml",
                "restart_policy": "never",
                "config": {
                    "mqtt": {"server": "mqtt://127.0.0.1:1883", "base_topic": "zigbee2mqtt"},
                    "serial": {"port": "/dev/ttyUSB0", "adapter": "ember"},
                    "runtime": "docker",
                    "data_path": "/tmp",
                },
                "mqtt_check": {"server": "mqtt://127.0.0.1:1883", "dry_run": True},
            },
        )
        final_snapshot_response = await client.get("/v1/snapshot")

    assert render_response.status_code == 200
    rendered = render_response.json()
    assert 'port: "COM4"' in rendered["yaml"]
    assert rendered["runtime"] == "native"

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["configured"] is True
    assert snapshot["adapter_path"] == "COM4"
    assert snapshot["adapter_hint"] == "zstack"

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

    assert final_snapshot_response.status_code == 200
    final_snapshot = final_snapshot_response.json()
    assert final_snapshot["devices"]["status"] == "planned"
    assert final_snapshot["network_map"]["status"] == "planned"
    assert final_snapshot["permit_join"]["status"] == "planned"
