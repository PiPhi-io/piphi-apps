from __future__ import annotations

import json
from pathlib import Path

from piphi_network_sense.contract import CAPABILITIES, COMMANDS
from piphi_network_sense.state import automations


def _catalog() -> dict:
    return json.loads((Path(__file__).parents[1] / "src" / "behaviors.json").read_text())


def test_behavior_catalog_covers_monitor_and_detected_appliances() -> None:
    catalog = _catalog()
    devices = {device["id"]: device for device in catalog["devices"]}

    assert catalog["behaviorSchemaVersion"] == "integration.behaviors.v2"
    assert set(devices) == {"sense_energy_monitor", "sense_detected_appliance"}
    assert devices["sense_energy_monitor"]["entityType"] == "energy_monitor"
    assert devices["sense_detected_appliance"]["entityType"] == "energy_device"
    assert {
        "device_power_w",
        "device_on",
        "device_daily_energy_kwh",
    } == set(devices["sense_detected_appliance"]["capabilities"])
    appliance_triggers = {
        trigger["id"]: trigger["runtime"]["event"]
        for trigger in devices["sense_detected_appliance"]["triggers"]
    }
    assert appliance_triggers == {
        "appliance_power_changed": "device.state_changed",
        "appliance_turned_on": "device.power.turned_on",
        "appliance_turned_off": "device.power.turned_off",
    }


def test_behavior_options_reference_runtime_capabilities_and_events() -> None:
    catalog = _catalog()
    mappings = {
        mapping["capability"]: mapping["nativeMetric"]
        for mapping in catalog["telemetry"]["capabilityMappings"]
    }
    assert len(mappings) == len(catalog["telemetry"]["capabilityMappings"])
    for capability, native_metric in mappings.items():
        assert capability.startswith("sensor.")
        assert native_metric in CAPABILITIES or (native_metric, capability) == (
            "is_on",
            "sensor.device_on",
        )

    for device in catalog["devices"]:
        assert set(device["capabilities"]).issubset(CAPABILITIES)
        for trigger in device["triggers"]:
            assert trigger["capability"] in mappings
            assert trigger["runtime"]["event"] in {
                "device.state_changed",
                "device.power.turned_on",
                "device.power.turned_off",
            }
            assert trigger["runtime"]["source"] == "integration"
            assert trigger["freshness"]["staleDataMode"] == "block"
        for condition in device["conditions"]:
            assert condition["capability"] in mappings
            assert condition["runtime"]["field"] == mappings[condition["capability"]]
            assert condition["freshness"]["maxAgeSeconds"] > 0
        for action in device["actions"]:
            assert action["runtime"]["command"] in COMMANDS
            assert action["runtime"]["endpoint"] == "/command"
            assert action["safety"]["riskLevel"] == "low"


def test_runtime_sdk_nodes_match_the_behavior_catalog() -> None:
    assert {definition.command for definition in automations.action_definitions} == {"refresh"}
    assert {definition.event_type for definition in automations.event_definitions} == {
        "device.state_changed",
        "device.power.turned_on",
        "device.power.turned_off",
    }
    snapshot = automations.contract_snapshot()
    assert snapshot["actions"][0]["result_schema"] == {
        "state": {"type": "object"}
    }
