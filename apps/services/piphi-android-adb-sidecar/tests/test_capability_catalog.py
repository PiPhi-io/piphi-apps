from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_android_adb_sidecar.main import app


ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "capability-catalog.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
EXAMPLE = json.loads((ROOT / "examples" / "entity-response.json").read_text())
ROLES = ("state", "events", "conditions", "actions")


def _by_status(status: str, role: str) -> set[str]:
    return {item for group in CATALOG["groups"] if group["status"] == status for item in group[role]}


def test_catalog_is_reviewable_and_duplicate_free() -> None:
    assert CATALOG["integration_id"] == MANIFEST["id"]
    assert {group["status"] for group in CATALOG["groups"]} <= {"implemented", "planned", "excluded"}
    for group in CATALOG["groups"]:
        assert group["scope"] and group["source_refs"] and group["reason"]
        assert set(group["source_refs"]) <= set(CATALOG["sources"])
    for role in ROLES:
        items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(items) == len(set(items)), f"duplicate {role}"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented = _by_status("implemented", "state") | _by_status("implemented", "actions")
    actions = _by_status("implemented", "actions")
    assert set(MANIFEST["capabilities"]) == implemented
    assert set(MANIFEST["commands"]) == actions
    assert {item for entity in MANIFEST["entities"] for item in entity["capabilities"]} == implemented
    assert {item["id"] for entity in MANIFEST["entities"] for item in entity["available_commands"]} == actions
    assert set(EXAMPLE["capabilities"]) == implemented
    assert set(EXAMPLE["commands"]) == actions


def test_sidecar_has_only_a_transport_service_entity() -> None:
    assert not (ROOT / "src" / "behaviors.json").exists()
    assert len(MANIFEST["entities"]) == 1
    assert MANIFEST["entities"][0]["id"] == "android-adb-service"
    assert MANIFEST["entities"][0]["entity_type"] == "service"


@pytest.mark.anyio
async def test_config_apply_emits_runtime_event() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            assert (await client.post("/config", json={"id": "catalog-test", "host": "127.0.0.1", "alias": "ADB"})).status_code == 200
            events = (await client.get("/events")).json()["events"]
            assert any(event["event_type"] == "runtime.config.applied" for event in events)
        finally:
            await client.post("/deconfigure/catalog-test")


@pytest.mark.anyio
@pytest.mark.parametrize("command", ["restart_worker", "execute_arbitrary_shell", "install_arbitrary_apk"])
async def test_unimplemented_and_unsafe_commands_fail_closed(command: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/command", json={"contract_version": "automation.runtime.command.v1", "command": command, "target": {"device_id": "android-adb-service", "config_id": "android-adb-service"}, "params": {}})
    assert response.status_code == 400
    assert response.json()["detail"] == f"Unsupported command: {command}"
