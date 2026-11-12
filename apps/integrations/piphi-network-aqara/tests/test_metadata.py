from __future__ import annotations

import json
from pathlib import Path

from piphi_network_aqara import runtime as runtime_module


def test_manifest_and_behaviors_align() -> None:
    root = Path(__file__).resolve().parent.parent / "src"
    manifest = json.loads((root / "manifest.json").read_text())
    behaviors = json.loads((root / "behaviors.json").read_text())

    manifest_capabilities = set(manifest["entities"][0]["capabilities"])
    behavior_capabilities = set(behaviors["devices"][0]["capabilities"])
    behavior_actions = {item["id"] for item in behaviors["devices"][0]["actions"]}

    assert manifest["id"] == "aqara-open-api"
    assert manifest["api"]["endpoints"]["config_sync"] == "/configs/sync"
    assert behavior_capabilities == manifest_capabilities
    assert {"refresh", "turn_on", "turn_off", "open", "close", "set_position", "set_brightness"} <= behavior_actions
    assert "stop" not in behavior_actions


def test_manifest_declares_auditable_core_security_event_coverage() -> None:
    root = Path(__file__).resolve().parents[1] / "src"
    manifest = json.loads((root / "manifest.json").read_text())
    security = manifest["security"]
    mappings = security["event_mappings"]

    assert security["contract_version"] == "1"
    assert len({mapping["source_event_type"] for mapping in mappings}) == len(mappings)
    assert all(mapping["device_models"] for mapping in mappings)
    assert all(mapping["required_permissions"] for mapping in mappings)

    implemented = {
        mapping["source_event_type"]: mapping["canonical_event_type"]
        for mapping in mappings
        if mapping["status"] == "implemented"
    }
    assert implemented == {
        "aqara.safety.smoke.detected": "safety_smoke_detected",
        "aqara.safety.smoke.cleared": "safety_smoke_cleared",
        "aqara.safety.leak.detected": "safety_leak_detected",
        "aqara.safety.leak.cleared": "safety_leak_cleared",
        "aqara.access.forced_open": "access_forced_open",
        "aqara.access.forced_open.cleared": "access_forced_open_cleared",
        "aqara.access.lock_jammed": "access_lock_jammed",
        "aqara.access.lock_jam.cleared": "access_lock_jam_cleared",
    }
    assert {
        mapping["source_event_type"]
        for mapping in mappings
        if mapping["status"] == "excluded"
    } == {"aqara.safety.gas.detected", "aqara.safety.gas.cleared"}


def test_automation_registry_matches_declared_behavior_commands() -> None:
    root = Path(__file__).resolve().parent.parent / "src"
    behaviors = json.loads((root / "behaviors.json").read_text())
    declared_commands = {
        action["runtime"]["command"]
        for device in behaviors["devices"]
        for action in device.get("actions", [])
    }
    registered_commands = {
        definition.command
        for definition in runtime_module.automation_registry.action_definitions
    }

    assert registered_commands == declared_commands
