from __future__ import annotations

import json
from pathlib import Path

from piphi_network_zigbee.contract import CAPABILITIES, COMMANDS

BEHAVIOR_PATH = Path(__file__).resolve().parents[1] / "src" / "behaviors.json"


def _payload() -> dict:
    return json.loads(BEHAVIOR_PATH.read_text(encoding="utf-8"))


def test_behavior_actions_match_runtime_commands_and_are_single_target() -> None:
    payload = _payload()
    assert payload["behaviorSchemaVersion"] == "integration.behaviors.v2"
    assert len(payload["devices"]) == 1
    actions = payload["devices"][0]["actions"]
    assert {item["runtime"]["command"] for item in actions} == set(COMMANDS)
    for action in actions:
        assert action["safety"]["fanoutSafe"] is False
        if action["id"] != "refresh":
            assert action["safety"]["requiresConfirmation"] is True
            assert action["safety"]["idempotency"] == "runtime_ledger"


def test_behavior_triggers_reference_implemented_capabilities_and_events() -> None:
    triggers = _payload()["devices"][0]["triggers"]
    assert {item["runtime"]["event"] for item in triggers} == {
        "device.state_changed",
        "zigbee.safety.smoke.detected",
        "zigbee.safety.carbon_monoxide.detected",
        "zigbee.safety.leak.detected",
    }
    for trigger in triggers:
        capability = trigger["capability"].split(".", 1)[-1]
        assert capability == "state" or capability in CAPABILITIES
        assert trigger["freshness"]["staleDataMode"] == "block"


def test_no_template_advertises_unnegotiated_control() -> None:
    assert _payload()["templates"] == []
