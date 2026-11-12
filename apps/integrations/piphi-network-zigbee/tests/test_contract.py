from __future__ import annotations

import json
from pathlib import Path

from piphi_network_zigbee.contract import COMMANDS, REQUIRED_ENDPOINTS
from piphi_network_zigbee.main import app
from piphi_network_zigbee.settings import INTEGRATION_VERSION


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


def test_manifest_declares_fail_closed_security_coverage() -> None:
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "src" / "manifest.json").read_text()
    )
    assert INTEGRATION_VERSION == manifest["version"]
    mappings = manifest["security"]["event_mappings"]

    assert manifest["security"]["contract_version"] == "1"
    assert len({mapping["source_event_type"] for mapping in mappings}) == len(mappings)
    assert all(mapping["device_models"] for mapping in mappings)
    assert all(mapping["required_permissions"] for mapping in mappings)
    assert {
        mapping["source_event_type"]
        for mapping in mappings
        if mapping["status"] == "implemented"
    } == {
        "zigbee.safety.smoke.detected",
        "zigbee.safety.smoke.cleared",
        "zigbee.safety.carbon_monoxide.detected",
        "zigbee.safety.carbon_monoxide.cleared",
        "zigbee.safety.leak.detected",
        "zigbee.safety.leak.cleared",
    }
    assert {
        mapping["source_event_type"]
        for mapping in mappings
        if mapping["status"] == "excluded"
    } == {
        "zigbee.security.tamper.detected",
        "zigbee.safety.gas.detected",
        "zigbee.contact.opened",
    }
