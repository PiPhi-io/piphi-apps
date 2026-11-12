from __future__ import annotations

import json
from pathlib import Path

from piphi_runtime_kit_python import (
    assert_behaviors_contract,
    build_mock_automation_event,
)

from solar_edge.contract import CAPABILITIES, COMMANDS
from solar_edge.state import automations


def _catalog() -> dict:
    return json.loads(
        (Path(__file__).parents[1] / "src" / "behaviors.json").read_text()
    )


def test_behavior_catalog_maps_real_solaredge_metrics() -> None:
    catalog = _catalog()
    assert catalog["behaviorSchemaVersion"] == "integration.behaviors.v2"
    assert catalog["templates"] == []

    mappings = {
        item["capability"]: item["nativeMetric"]
        for item in catalog["telemetry"]["capabilityMappings"]
    }
    assert len(mappings) == len(catalog["telemetry"]["capabilityMappings"])
    assert set(mappings.values()).issubset(CAPABILITIES)

    device = catalog["devices"][0]
    assert device["id"] == "solar_edge_site"
    assert set(device["capabilities"]) == set(CAPABILITIES)
    assert device["targeting"]["fanout"]["supported"] is False

    for trigger in device["triggers"]:
        assert trigger["capability"] in mappings
        assert trigger["runtime"] == {
            "event": "device.state_changed",
            "source": "integration",
        }
    for condition in device["conditions"]:
        assert condition["runtime"]["field"] == mappings[condition["capability"]]
        assert condition["freshness"]["staleDataMode"] == "block"
    for action in device["actions"]:
        assert action["runtime"]["command"] in COMMANDS
        assert action["targeting"]["supportsMultiTarget"] is False
        assert action["failure"]["idempotent"] is True


def test_runtime_sdk_contract_matches_behaviors() -> None:
    assert_behaviors_contract(_catalog(), automations)
    assert {item.command for item in automations.action_definitions} == {"refresh"}
    assert {item.event_type for item in automations.event_definitions} == {
        "device.state_changed"
    }
    snapshot = automations.contract_snapshot()
    assert snapshot["actions"][0]["parameter_schema"] == {}
    assert snapshot["actions"][0]["result_schema"] == {
        "state": {"type": "object"}
    }
    assert snapshot["events"][0]["data_schema"] == {
        "capabilities": {"type": "array"},
        "changed_metrics": {"type": "array"},
    }


def test_runtime_event_fixture_has_core_identity() -> None:
    event = build_mock_automation_event(
        "device.state_changed",
        data={"changed_metrics": ["production_power_w"]},
        integration_id="piphi-network-solaredge",
        config_id="site-one",
        device_id="solaredge-1234567",
    )
    payload = event.model_dump(mode="json")
    assert payload["type"] == "device.state_changed"
    assert payload["integration_id"] == "piphi-network-solaredge"
    assert payload["config_id"] == "site-one"
    assert payload["data"]["changed_metrics"] == ["production_power_w"]
