from __future__ import annotations

import json
from pathlib import Path

from piphi_network_zigbee2mqtt.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_zigbee2mqtt.main import app


def test_runtime_implements_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    for path in [
        "/health",
        "/diagnostics",
        "/discover",
        "/config",
        "/config/sync",
        "/deconfigure",
        "/deconfigure/{config_id}",
        "/ui-config",
        "/entities",
        "/state",
        "/contract",
        "/events",
        "/events/device/{config_id}/example",
        "/telemetry/example",
        "/telemetry/device/{config_id}/example",
        "/command",
        "/v1/snapshot",
        "/v1/adapters",
        "/v1/coordinator/probe",
        "/v1/network-backup",
        "/v1/network-backup/export",
        "/v1/network-backup/import",
        "/v1/network-restore",
        "/v1/coordinator-migration/plan",
        "/v1/coordinator-migration/apply",
        "/v1/config/render",
        "/v1/config/write",
        "/v1/apply",
        "/v1/supervisor/status",
        "/v1/supervisor/start",
        "/v1/supervisor/stop",
        "/v1/supervisor/restart",
        "/v1/supervisor/logs",
        "/v1/prerequisites",
        "/v1/mqtt/check",
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS


def test_linux_runtime_is_unprivileged_and_has_no_host_control_mounts() -> None:
    manifest = json.loads(
        (Path(__file__).parents[1] / "src" / "manifest.json").read_text(encoding="utf-8")
    )
    container = manifest["runtime"]["linux"]["container"]

    assert container["privileged"] is False
    assert container["devices"] == []
    assert container["volumes"] == [
        {
            "host": "piphi-helper-zigbee2mqtt-data",
            "container": "/app/data",
            "mode": "rw",
        }
    ]
    serialized = json.dumps(container)
    assert "/var/run/docker.sock" not in serialized
    assert "/dev/bus/usb" not in serialized
