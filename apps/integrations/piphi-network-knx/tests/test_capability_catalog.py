from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_knx.main import app

ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "capability-catalog.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
BEHAVIORS = json.loads((ROOT / "src" / "behaviors.json").read_text())
ROLES = ("state", "events", "conditions", "actions")
STATUSES = {"implemented", "planned", "excluded"}


def _by_status(status: str, role: str) -> set[str]:
    return {
        item for group in CATALOG["groups"] if group["status"] == status for item in group[role]
    }


def test_catalog_is_reviewable_and_has_no_duplicate_role_entries() -> None:
    assert CATALOG["catalog_version"] == "1.1"
    assert CATALOG["integration_id"] == MANIFEST["id"]
    assert {group["status"] for group in CATALOG["groups"]} <= STATUSES
    for group in CATALOG["groups"]:
        assert group["scope"] and group["source_refs"] and group["reason"]
        assert set(group["source_refs"]) <= set(CATALOG["sources"])
    for role in ROLES:
        all_items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(all_items) == len(set(all_items)), f"duplicate {role} catalog entries"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented = _by_status("implemented", "state") | _by_status("implemented", "actions")
    actions = _by_status("implemented", "actions")
    manifest_capabilities = set(MANIFEST["capabilities"])
    entity_capabilities = {
        capability for entity in MANIFEST["entities"] for capability in entity["capabilities"]
    }
    behavior_capabilities = {
        capability for device in BEHAVIORS["devices"] for capability in device["capabilities"]
    }
    assert manifest_capabilities == entity_capabilities == behavior_capabilities == implemented
    assert set(MANIFEST["commands"]) == actions
    assert {
        action["id"] for device in BEHAVIORS["devices"] for action in device["actions"]
    } == actions


def test_implemented_behavior_events_and_conditions_are_declared() -> None:
    behavior_events = {
        trigger["runtime"]["event"]
        for device in BEHAVIORS["devices"]
        for trigger in device["triggers"]
    }
    behavior_conditions = {
        condition["id"] for device in BEHAVIORS["devices"] for condition in device["conditions"]
    }
    assert behavior_events == _by_status("implemented", "events")
    assert behavior_conditions == _by_status("implemented", "conditions")


@pytest.mark.anyio
@pytest.mark.parametrize("command", ["set_power", "identify", "send_arbitrary_telegram"])
async def test_unimplemented_and_unsafe_commands_fail_closed(command: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            json={"command": command, "config_id": "not-configured", "params": {}},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == f"Unsupported command: {command}"
