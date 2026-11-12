from __future__ import annotations

import json
from pathlib import Path

from piphi_network_weatherxm.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_weatherxm.main import app


ROOT = Path(__file__).resolve().parents[1]


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
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS


def test_behavior_contract_is_release_ready() -> None:
    behavior = json.loads((ROOT / "src" / "behaviors.json").read_text())
    assert behavior["behaviorSchemaVersion"] == "integration.behaviors.v2"

    device_ids = {device["id"] for device in behavior["devices"]}
    assert device_ids

    for device in behavior["devices"]:
        action_ids: set[str] = set()
        for action in device.get("actions", []):
            assert action["id"] not in action_ids
            action_ids.add(action["id"])
            assert action.get("runtime", {}).get("command")
            assert action.get("safety", {}).get("riskLevel") in {"low", "medium", "high", "critical"}

    for template in behavior.get("templates", []):
        assert template.get("deviceKey") in device_ids
        assert template.get("config", {}).get("automation_schema_version") in {
            "automation.behavior.v1",
            "automation.behavior.v2",
        }
