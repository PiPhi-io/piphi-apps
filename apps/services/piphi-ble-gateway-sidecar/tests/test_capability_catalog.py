from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_ble_gateway_sidecar.main import app


ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "capability-catalog.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
ENTITY_EXAMPLE = json.loads((ROOT / "examples" / "entity-response.json").read_text())
ROLES = ("state", "events", "conditions", "actions")
STATUSES = {"implemented", "planned", "excluded"}


def _by_status(status: str, role: str) -> set[str]:
    return {item for group in CATALOG["groups"] if group["status"] == status for item in group[role]}


def test_catalog_is_reviewable_and_has_no_duplicate_role_entries() -> None:
    assert CATALOG["catalog_version"] == "1.0"
    assert CATALOG["integration_id"] == MANIFEST["id"]
    assert CATALOG["coverage_mode"] and CATALOG["sources"]
    assert {group["status"] for group in CATALOG["groups"]} <= STATUSES
    for group in CATALOG["groups"]:
        assert group["scope"] and group["source_refs"] and group["reason"]
        assert set(group["source_refs"]) <= set(CATALOG["sources"])
        for role in ROLES:
            assert len(group[role]) == len(set(group[role]))
    for role in ROLES:
        items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(items) == len(set(items)), f"duplicate {role} catalog entries"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented = _by_status("implemented", "state") | _by_status("implemented", "actions")
    actions = _by_status("implemented", "actions")
    unavailable = {item for status in ("planned", "excluded") for role in ROLES for item in _by_status(status, role)}
    entity_capabilities = {item for entity in MANIFEST["entities"] for item in entity["capabilities"]}
    entity_commands = {item["id"] for entity in MANIFEST["entities"] for item in entity["available_commands"]}
    assert set(MANIFEST["capabilities"]) == implemented
    assert set(MANIFEST["commands"]) == actions
    assert entity_capabilities == implemented
    assert entity_commands == actions
    assert set(ENTITY_EXAMPLE["capabilities"]) == implemented
    assert set(ENTITY_EXAMPLE["commands"]) == actions
    assert not unavailable & (set(MANIFEST["capabilities"]) | set(MANIFEST["commands"]))


def test_sidecar_has_only_a_transport_service_entity() -> None:
    assert not (ROOT / "src" / "behaviors.json").exists()
    assert len(MANIFEST["entities"]) == 1
    service = MANIFEST["entities"][0]
    assert service["id"] == "ble-gateway-service"
    assert service["entity_type"] == "service"
    assert not _by_status("implemented", "conditions")


@pytest.mark.anyio
async def test_config_apply_emits_the_implemented_event() -> None:
    transport = httpx.ASGITransport(app=app)
    config_id = "capability-catalog-test"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            response = await client.post("/config", json={"id": config_id, "host": "127.0.0.1", "alias": "Coverage Test"})
            assert response.status_code == 200
            events = (await client.get("/events")).json()["events"]
            assert any(event["event_type"] == "runtime.config.applied" and event["config_id"] == config_id for event in events)
        finally:
            await client.post(f"/deconfigure/{config_id}")


@pytest.mark.anyio
@pytest.mark.parametrize("command", ["restart_worker", "write_arbitrary_characteristic", "execute_arbitrary_dbus_method"])
async def test_unimplemented_and_unsafe_commands_fail_closed(command: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/command", json={"contract_version": "automation.runtime.command.v1", "command": command, "target": {"device_id": "ble-gateway-service", "config_id": "ble-gateway-service"}, "params": {}})
    assert response.status_code == 400
    assert response.json()["detail"] == f"Unsupported command: {command}"
