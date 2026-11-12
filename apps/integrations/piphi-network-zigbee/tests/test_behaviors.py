from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from piphi_network_zigbee.contract import CAPABILITIES, COMMANDS


BEHAVIOR_PATH = Path(__file__).resolve().parents[1] / "src" / "behaviors.json"
ALLOWED_PARAMETER_TYPES = {"number", "boolean", "text", "enum", "duration"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "critical"}
ALLOWED_STALE_DATA_MODES = {"allow", "block"}
EXPECTED_IMPLEMENTED_COMMANDS = {"refresh", "set_state", "set_brightness", "set_color_temperature"}
FAMILY_CAPABILITY_EXPECTATIONS = {
    "lights": {"state", "brightness_percent", "color_temperature_mired"},
    "switches": {"state"},
    "plugs": {"state", "power_w", "energy_kwh"},
    "dimmers": {"brightness_percent"},
    "remotes": {"action"},
    "scene_controllers": {"action"},
    "motion_sensors": {"occupancy"},
    "presence_sensors": {"occupancy"},
    "contact_sensors": {"contact_open"},
    "temperature_sensors": {"temperature_c"},
    "humidity_sensors": {"humidity_percent"},
    "illuminance_sensors": {"illuminance_lux"},
    "pressure_sensors": {"pressure_hpa"},
    "leak_sensors": {"water_leak"},
    "smoke_sensors": {"smoke"},
    "gas_sensors": {"gas"},
    "carbon_monoxide_sensors": {"carbon_monoxide"},
    "tamper_sensors": {"tamper"},
    "power_meters": {"power_w", "energy_kwh", "current_a", "voltage_v"},
    "covers": {"position_percent"},
    "shades": {"position_percent"},
    "blinds": {"position_percent"},
    "valves": {"position_percent"},
}


def _load_behaviors() -> dict[str, Any]:
    return json.loads(BEHAVIOR_PATH.read_text())


def _behavior_device(payload: dict[str, Any]) -> dict[str, Any]:
    devices = payload.get("devices") or []
    assert len(devices) == 1
    return devices[0]


_PAYLOAD = _load_behaviors()
_DEVICE = _behavior_device(_PAYLOAD)
_CAPABILITIES = tuple(_DEVICE["capabilities"])
_TRIGGERS = tuple(_DEVICE["triggers"])
_INTENTS = tuple(_DEVICE["intents"])
_CONDITIONS = tuple(_DEVICE["conditions"])
_ACTIONS = tuple(_DEVICE["actions"])
_TEMPLATES = tuple(_PAYLOAD["templates"])
_STOP_OPTIONS = tuple(_DEVICE["stop"])
_MANUAL_OVERRIDES = tuple(_DEVICE["manualOverride"])
_SUPPORTED_FAMILIES = tuple(_DEVICE["metadata"]["supportedFamilies"])
_KNOWN_FAMILIES = tuple(_DEVICE["metadata"]["knownZigbee2mqttFamilies"])
_READ_ONLY_COMMANDS = tuple(_DEVICE["metadata"]["runtimeActionCoverage"]["readOnlyUntilRuntimeCommandsExist"])


def _option_id(value: dict[str, Any]) -> str:
    return str(value.get("id") or "unknown")


def _template_id(value: dict[str, Any]) -> str:
    return str(value.get("id") or "unknown")


def _capability_id(value: str) -> str:
    return value


def _family_id(value: str) -> str:
    return value


def _validate_behavior_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    devices = payload.get("devices") if isinstance(payload.get("devices"), list) else []
    templates = payload.get("templates") if isinstance(payload.get("templates"), list) else []
    device_ids = {device.get("id") for device in devices if isinstance(device, dict)}
    options_by_device: dict[str, dict[str, set[str]]] = {}

    for index, device in enumerate(devices):
        if not isinstance(device, dict):
            errors.append(f"devices[{index}] must be an object")
            continue

        device_id = str(device.get("id") or "")
        options_by_device[device_id] = {
            "triggers": {option.get("id") for option in device.get("triggers", []) if isinstance(option, dict)},
            "actions": {option.get("id") for option in device.get("actions", []) if isinstance(option, dict)},
        }

        for capability in device.get("capabilities", []):
            if capability not in CAPABILITIES:
                errors.append(f"{device_id} exposes unknown capability {capability}")

        for action in device.get("actions", []):
            if not isinstance(action, dict):
                continue
            command = (action.get("runtime") or {}).get("command")
            if not command:
                errors.append(f"{device_id}.{action.get('id')} is missing runtime.command")
            elif command not in COMMANDS:
                errors.append(f"{device_id}.{action.get('id')} uses unknown command {command}")

            risk_level = (action.get("safety") or {}).get("riskLevel") or action.get("riskLevel")
            if not risk_level:
                errors.append(f"{device_id}.{action.get('id')} is missing safety.riskLevel")

    for index, template in enumerate(templates):
        if not isinstance(template, dict):
            errors.append(f"templates[{index}] must be an object")
            continue

        device_key = template.get("deviceKey")
        if device_key not in device_ids:
            errors.append(f"{template.get('id')} references unknown device {device_key}")
            continue

        valid_options = options_by_device[device_key]
        config = template.get("config") or {}
        trigger_refs = [
            trigger.get("sourceRef", {}).get("optionKey") or trigger.get("id")
            for trigger in config.get("triggers", [])
            if isinstance(trigger, dict)
        ]
        if isinstance(config.get("trigger"), dict):
            trigger_refs.append(config["trigger"].get("sourceRef", {}).get("optionKey") or config["trigger"].get("id"))
        for trigger_ref in trigger_refs:
            if trigger_ref and trigger_ref not in valid_options["triggers"]:
                errors.append(f"{template.get('id')} references unknown trigger {trigger_ref}")

        for action in config.get("actions", []):
            if not isinstance(action, dict):
                continue
            action_ref = action.get("sourceRef", {}).get("optionKey") or action.get("action")
            if action_ref and action_ref not in valid_options["actions"]:
                errors.append(f"{template.get('id')} references unknown action {action_ref}")

    return errors


def test_behavior_catalog_happy_path_matches_runtime_contract() -> None:
    payload = _load_behaviors()
    device = _behavior_device(payload)

    assert payload["behaviorSchemaVersion"] == "integration.behaviors.v2"
    assert _validate_behavior_payload(payload) == []
    assert len(payload["templates"]) == 6
    assert len(device["capabilities"]) == 29
    assert len(device["triggers"]) == 12
    assert len(device["conditions"]) == 6

    action_commands = {
        action["runtime"]["command"]
        for action in device["actions"]
    }
    assert action_commands == {"refresh", "set_state", "set_brightness", "set_color_temperature"}


@pytest.mark.parametrize("capability", _CAPABILITIES, ids=_capability_id)
def test_each_declared_capability_is_known_to_runtime(capability: str) -> None:
    runtime_capability = CAPABILITIES[capability]

    assert runtime_capability["kind"] in {"sensor", "actuator", "action"}
    if runtime_capability["kind"] in {"sensor", "actuator"}:
        assert runtime_capability.get("unit")


@pytest.mark.parametrize("capability", _CAPABILITIES, ids=_capability_id)
def test_each_declared_capability_is_unique(capability: str) -> None:
    assert _CAPABILITIES.count(capability) == 1


@pytest.mark.parametrize("trigger", _TRIGGERS, ids=_option_id)
def test_each_trigger_has_runtime_event_and_freshness(trigger: dict[str, Any]) -> None:
    runtime = trigger.get("runtime") or {}
    freshness = trigger.get("freshness") or {}

    assert trigger["id"]
    assert trigger["label"]
    assert trigger["description"]
    assert runtime.get("event") == "device.state_changed"
    assert runtime.get("source") == "integration"
    assert freshness["maxAgeSeconds"] > 0
    assert freshness["staleDataMode"] in ALLOWED_STALE_DATA_MODES


@pytest.mark.parametrize("trigger", _TRIGGERS, ids=_option_id)
def test_each_trigger_references_known_capability_namespace(trigger: dict[str, Any]) -> None:
    capability = trigger["capability"]

    assert capability.startswith("telemetry.")
    assert (trigger.get("ui") or {}).get("group")


@pytest.mark.parametrize("intent", _INTENTS, ids=_option_id)
def test_each_intent_is_user_readable(intent: dict[str, Any]) -> None:
    assert intent["id"]
    assert intent["label"]
    assert intent["description"]


@pytest.mark.parametrize("condition", _CONDITIONS, ids=_option_id)
def test_each_condition_has_valid_params_and_freshness(condition: dict[str, Any]) -> None:
    freshness = condition.get("freshness") or {}

    assert condition["id"]
    assert condition["label"]
    assert condition["description"]
    assert condition["type"] in ALLOWED_PARAMETER_TYPES
    assert condition["operators"]
    assert freshness["maxAgeSeconds"] > 0
    assert freshness["staleDataMode"] in ALLOWED_STALE_DATA_MODES
    for parameter in condition.get("params", []):
        assert parameter["name"]
        assert parameter["label"]
        assert parameter["type"] in ALLOWED_PARAMETER_TYPES
        if parameter["type"] == "enum":
            assert parameter["options"]
            if "default" in parameter:
                assert parameter["default"] in parameter["options"]


@pytest.mark.parametrize("action", _ACTIONS, ids=_option_id)
def test_each_action_maps_to_implemented_runtime_command(action: dict[str, Any]) -> None:
    command = action["runtime"]["command"]

    assert command in EXPECTED_IMPLEMENTED_COMMANDS
    assert command in COMMANDS
    assert action["runtime"]["endpoint"] == "/command"
    assert action["runtime"]["method"] == "POST"
    assert action["runtime"]["timeoutSeconds"] > 0


@pytest.mark.parametrize("action", _ACTIONS, ids=_option_id)
def test_each_action_has_safety_failure_and_targeting_policy(action: dict[str, Any]) -> None:
    safety = action.get("safety") or {}
    failure = action.get("failure") or {}
    targeting = action.get("targeting") or {}

    assert safety["riskLevel"] in ALLOWED_RISK_LEVELS
    assert isinstance(safety["liveRunAllowed"], bool)
    assert failure["strategy"] == "retry_then_continue"
    assert failure["retry"]["maxAttempts"] >= 1
    assert failure["timeoutSeconds"] > 0
    assert targeting["fanoutSafe"] is True
    assert targeting["supportsMultiTarget"] is True
    assert "selection" in targeting["scopes"]


@pytest.mark.parametrize("template", _TEMPLATES, ids=_template_id)
def test_each_template_references_existing_options(template: dict[str, Any]) -> None:
    trigger_ids = {trigger["id"] for trigger in _TRIGGERS}
    action_ids = {action["id"] for action in _ACTIONS}
    config = template["config"]
    trigger_refs = {
        trigger.get("sourceRef", {}).get("optionKey") or trigger.get("id")
        for trigger in config.get("triggers", [])
    }
    action_refs = {
        action.get("sourceRef", {}).get("optionKey") or action.get("action")
        for action in config.get("actions", [])
    }

    assert template["deviceKey"] == _DEVICE["id"]
    assert trigger_refs
    assert action_refs
    assert trigger_refs.issubset(trigger_ids)
    assert action_refs.issubset(action_ids)


@pytest.mark.parametrize("template", _TEMPLATES, ids=_template_id)
def test_each_template_has_runtime_execution_policy(template: dict[str, Any]) -> None:
    config = template["config"]
    policies = config.get("policies") or {}

    assert config["automation_schema_version"] == "automation.behavior.v2"
    assert config["execution"]["dispatchMode"] == "runtime"
    assert policies["execution"]["dispatchMode"] == "runtime"
    assert policies["manualOverride"]["mode"] == "continue"
    assert isinstance(policies["cooldownSeconds"], int)


@pytest.mark.parametrize("family", _SUPPORTED_FAMILIES, ids=_family_id)
def test_each_supported_family_has_capability_coverage(family: str) -> None:
    expected_capabilities = FAMILY_CAPABILITY_EXPECTATIONS[family]

    assert expected_capabilities.intersection(_CAPABILITIES)


@pytest.mark.parametrize("family", _KNOWN_FAMILIES, ids=_family_id)
def test_each_known_family_is_either_supported_or_documented_as_future(family: str) -> None:
    aggregate_families = {"environment_sensors", "safety_sensors"}
    future_families = {"locks", "fans", "climate", "thermostats", "ir_remotes", "sirens", "custom_exposes"}

    assert family in _SUPPORTED_FAMILIES or family in aggregate_families or family in future_families


@pytest.mark.parametrize("command", _READ_ONLY_COMMANDS, ids=_capability_id)
def test_each_future_command_is_not_exposed_as_runtime_action(command: str) -> None:
    action_ids = {action["id"] for action in _ACTIONS}
    runtime_commands = {action["runtime"]["command"] for action in _ACTIONS}

    assert command not in action_ids
    assert command not in runtime_commands
    assert command not in COMMANDS


@pytest.mark.parametrize("stop_option", _STOP_OPTIONS, ids=_option_id)
def test_each_stop_option_is_valid(stop_option: dict[str, Any]) -> None:
    assert stop_option["id"]
    assert stop_option["label"]
    if "params" in stop_option:
        for parameter in stop_option["params"]:
            assert parameter["type"] in ALLOWED_PARAMETER_TYPES


@pytest.mark.parametrize("manual_override", _MANUAL_OVERRIDES, ids=_option_id)
def test_each_manual_override_is_valid(manual_override: dict[str, Any]) -> None:
    assert manual_override["id"]
    assert manual_override["label"]
    if "params" in manual_override:
        for parameter in manual_override["params"]:
            assert parameter["type"] in ALLOWED_PARAMETER_TYPES


def test_behavior_catalog_covers_common_zigbee2mqtt_expose_families() -> None:
    device = _behavior_device(_load_behaviors())
    families = set(device["metadata"]["knownZigbee2mqttFamilies"])
    supported_families = set(device["metadata"]["supportedFamilies"])

    assert {
        "lights",
        "switches",
        "plugs",
        "remotes",
        "motion_sensors",
        "presence_sensors",
        "contact_sensors",
        "environment_sensors",
        "safety_sensors",
        "power_meters",
        "covers",
        "locks",
        "fans",
        "climate",
        "thermostats",
        "custom_exposes",
    }.issubset(families)
    assert {
        "lights",
        "switches",
        "plugs",
        "motion_sensors",
        "contact_sensors",
        "power_meters",
        "covers",
        "valves",
    }.issubset(supported_families)


def test_future_write_families_are_documented_as_read_only_edge_cases() -> None:
    device = _behavior_device(_load_behaviors())
    metadata = device["metadata"]
    action_ids = {action["id"] for action in device["actions"]}
    read_only_commands = set(metadata["runtimeActionCoverage"]["readOnlyUntilRuntimeCommandsExist"])

    assert {
        "lock_unlock",
        "cover_position",
        "fan_mode",
        "climate_mode",
        "temperature_setpoint",
        "color_xy",
        "color_hs",
        "effect",
        "siren",
        "device_specific_write",
    }.issubset(read_only_commands)
    assert read_only_commands.isdisjoint(action_ids)


def test_negative_behavior_action_without_runtime_command_is_rejected() -> None:
    payload = _load_behaviors()
    broken = copy.deepcopy(payload)
    broken_device = _behavior_device(broken)
    del broken_device["actions"][0]["runtime"]["command"]

    assert "piphi_network_zigbee_device.refresh is missing runtime.command" in _validate_behavior_payload(broken)


def test_negative_template_with_unknown_option_reference_is_rejected() -> None:
    payload = _load_behaviors()
    broken = copy.deepcopy(payload)
    broken["templates"][0]["config"]["actions"][0]["sourceRef"]["optionKey"] = "unlock_door"
    broken["templates"][0]["config"]["triggers"][0]["sourceRef"]["optionKey"] = "zigbee_magic"

    errors = _validate_behavior_payload(broken)
    assert "refresh_on_state_change references unknown action unlock_door" in errors
    assert "refresh_on_state_change references unknown trigger zigbee_magic" in errors


def test_edge_templates_only_reference_implemented_runtime_actions() -> None:
    payload = _load_behaviors()
    device = _behavior_device(payload)
    implemented_actions = {action["id"] for action in device["actions"]}

    for template in payload["templates"]:
        for action in template["config"].get("actions", []):
            action_ref = action.get("sourceRef", {}).get("optionKey") or action.get("action")
            assert action_ref in implemented_actions
