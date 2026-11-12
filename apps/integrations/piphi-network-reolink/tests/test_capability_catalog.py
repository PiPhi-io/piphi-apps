from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_reolink.main import app

ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "capability-catalog.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
BEHAVIORS = json.loads((ROOT / "src" / "behaviors.json").read_text())
ENTITY_EXAMPLE = json.loads((ROOT / "examples" / "entity-response.json").read_text())
ROLES = ("state", "events", "conditions", "actions")
STATUSES = {"implemented", "planned", "excluded"}


def _by_status(status: str, role: str) -> set[str]:
    return {
        item for group in CATALOG["groups"] if group["status"] == status for item in group[role]
    }


def test_catalog_is_reviewable_and_has_unique_role_entries() -> None:
    assert CATALOG["integration_id"] == MANIFEST["id"]
    assert CATALOG["coverage_mode"]
    assert CATALOG["sources"]
    assert {group["status"] for group in CATALOG["groups"]} <= STATUSES
    for group in CATALOG["groups"]:
        assert group["scope"] and group["source_refs"] and group["reason"]
        assert set(group["source_refs"]) <= set(CATALOG["sources"])
        for role in ROLES:
            assert len(group[role]) == len(set(group[role]))
    for role in ROLES:
        all_items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(all_items) == len(set(all_items)), f"duplicate {role} entries"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented = _by_status("implemented", "state") | _by_status("implemented", "actions")
    actions = _by_status("implemented", "actions")
    planned_or_excluded = {
        item
        for status in ("planned", "excluded")
        for role in ROLES
        for item in _by_status(status, role)
    }
    manifest_capabilities = set(MANIFEST["capabilities"])
    manifest_commands = set(MANIFEST["commands"])
    entity_capabilities = {
        capability for entity in MANIFEST["entities"] for capability in entity["capabilities"]
    }
    behavior_capabilities = {
        capability for device in BEHAVIORS["devices"] for capability in device["capabilities"]
    }
    behavior_actions = {
        action["id"] for device in BEHAVIORS["devices"] for action in device["actions"]
    }
    assert manifest_capabilities == entity_capabilities == behavior_capabilities == implemented
    assert manifest_commands == behavior_actions == actions
    assert set(ENTITY_EXAMPLE["capabilities"]) == implemented
    assert set(ENTITY_EXAMPLE["commands"]) == actions
    assert not planned_or_excluded & (implemented | behavior_actions)


def test_behavior_events_and_conditions_match_catalog() -> None:
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
async def test_config_event_is_emitted_without_credentials() -> None:
    transport = httpx.ASGITransport(app=app)
    config_id = "catalog-test"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            response = await client.post(
                "/config",
                json={
                    "id": config_id,
                    "host": "192.0.2.30",
                    "username": "piphi",
                    "password": "catalog-secret",
                },
            )
            assert response.status_code == 200
            events = (await client.get("/events")).json()["events"]
            event = next(
                item
                for item in events
                if item["event_type"] == "runtime.config.applied" and item["config_id"] == config_id
            )
            assert "catalog-secret" not in str(event)
        finally:
            await client.post(f"/deconfigure/{config_id}")


@pytest.mark.anyio
@pytest.mark.parametrize("command", ["set_siren", "move_to_preset", "send_arbitrary_command"])
async def test_planned_and_unsafe_commands_fail_closed(command: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": command,
                "target": {"device_id": "missing", "config_id": "missing"},
                "params": {},
            },
        )
    assert response.status_code == 400
    assert response.json()["detail"] == f"Unsupported command: {command}"
