from __future__ import annotations

import json
from pathlib import Path

from piphi_network_plex.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_plex.main import app


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
        "/provider/instances",
        "/provider/{instance_id}/collections",
        "/provider/{instance_id}/items",
        "/provider/{instance_id}/resolve",
        "/provider/{instance_id}/actions",
        "/provider/{instance_id}/asset",
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS


def test_capability_catalog_matches_runtime_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "manifest.json").read_text())
    catalog = json.loads((root / "capability-catalog.json").read_text())
    implemented = {
        capability
        for row in catalog["rows"]
        if row["status"] == "implemented"
        for capability in row.get("capabilities", [])
    }
    unavailable = {
        capability
        for row in catalog["rows"]
        if row["status"] != "implemented"
        for capability in row.get("capabilities", [])
    }
    assert implemented <= set(manifest["capabilities"])
    assert unavailable.isdisjoint(manifest["capabilities"])
    assert len({row["id"] for row in catalog["rows"]}) == len(catalog["rows"])
    implemented_events = {
        event
        for row in catalog["rows"]
        if row["status"] == "implemented"
        for event in row.get("events", [])
    }
    behaviors = json.loads((root / "src/behaviors.json").read_text())
    behavior_events = {
        trigger["runtime"]["event"] for trigger in behaviors["devices"][0]["triggers"]
    }
    assert implemented_events == set(manifest["events"]) == behavior_events
    assert manifest["config"]["secret_fields"] == ["token"]
    assert "token" not in manifest["identity"]["fields"]
