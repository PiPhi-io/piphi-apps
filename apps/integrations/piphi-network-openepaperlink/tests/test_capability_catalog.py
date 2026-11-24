from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_openepaperlink import state
from piphi_network_openepaperlink.ap import AccessPointSnapshot
from piphi_network_openepaperlink.contract import AP_ENTITY_TEMPLATE
from piphi_network_openepaperlink.main import app
from piphi_network_openepaperlink.schemas import DeviceConfig

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
    assert CATALOG["catalog_version"] == "1.0"
    assert CATALOG["integration_id"] == MANIFEST["id"]
    assert CATALOG["coverage_mode"]
    assert CATALOG["sources"]
    assert {group["status"] for group in CATALOG["groups"]} <= STATUSES

    for group in CATALOG["groups"]:
        assert group["scope"]
        assert group["source_refs"]
        assert group["reason"]
        assert set(group["source_refs"]) <= set(CATALOG["sources"])
        for role in ROLES:
            assert len(group[role]) == len(set(group[role]))

    for role in ROLES:
        all_items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(all_items) == len(set(all_items)), f"duplicate {role} catalog entries"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented_capabilities = _by_status("implemented", "state") | _by_status(
        "implemented", "actions"
    )
    implemented_actions = _by_status("implemented", "actions")
    planned_or_excluded = {
        item
        for status in ("planned", "excluded")
        for role in ROLES
        for item in _by_status(status, role)
    }

    manifest_capabilities = set(MANIFEST["capabilities"])
    manifest_commands = set(MANIFEST["commands"])
    entity_capabilities = set(AP_ENTITY_TEMPLATE["capabilities"])
    entity_commands = {command["id"] for command in AP_ENTITY_TEMPLATE["available_commands"]}
    behavior_capabilities = {
        capability for device in BEHAVIORS["devices"] for capability in device["capabilities"]
    }
    behavior_actions = {
        action["id"] for device in BEHAVIORS["devices"] for action in device["actions"]
    }

    assert manifest_capabilities == implemented_capabilities
    assert manifest_commands == implemented_actions
    assert entity_capabilities == implemented_capabilities
    assert entity_commands == implemented_actions
    assert behavior_capabilities == implemented_capabilities
    assert behavior_actions == implemented_actions
    assert not planned_or_excluded & (
        manifest_capabilities
        | manifest_commands
        | entity_capabilities
        | entity_commands
        | behavior_actions
    )


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
async def test_config_apply_emits_the_implemented_behavior_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_id = "capability-catalog-test"

    async def fake_fetch(_host: str) -> AccessPointSnapshot:
        return AccessPointSnapshot(())

    monkeypatch.setattr(state, "snapshot_fetcher", fake_fetch)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    await state.apply_config(DeviceConfig(id=config_id, host="192.168.1.2", alias="Coverage Test"))
    try:
        assert any(
            event["event_type"] == "runtime.config.applied" and event["config_id"] == config_id
            for event in state.registry.recent_events
        )
    finally:
        await state.remove_config(config_id)


@pytest.mark.anyio
@pytest.mark.parametrize("command", ["set_power", "identify", "send_arbitrary_command"])
async def test_unimplemented_and_unsafe_commands_fail_closed(
    command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "test-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            headers={"X-PiPhi-Integration-Token": "test-token"},
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": command,
                "target": {"device_id": "demo-device", "config_id": "demo-device"},
                "params": {},
            },
        )
    assert response.status_code == 400
    assert response.json()["detail"] == f"Unsupported command: {command}"
