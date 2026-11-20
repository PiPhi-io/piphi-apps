from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_llm_vision.main import app


ROOT = Path(__file__).parents[1]
CATALOG = json.loads((ROOT / "capability-catalog.json").read_text())
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
ENTITY_EXAMPLE = json.loads((ROOT / "examples" / "entity-response.json").read_text())
ROLES = ("state", "events", "conditions", "actions")
STATUSES = {"implemented", "planned", "excluded"}


def _by_status(status: str, role: str) -> set[str]:
    return {
        item
        for group in CATALOG["groups"]
        if group["status"] == status
        for item in group[role]
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
        items = [item for group in CATALOG["groups"] for item in group[role]]
        assert len(items) == len(set(items)), f"duplicate {role} catalog entries"


def test_only_implemented_capabilities_are_advertised() -> None:
    implemented = _by_status("implemented", "state") | _by_status("implemented", "actions")
    implemented_actions = _by_status("implemented", "actions")
    unavailable = {
        item
        for status in ("planned", "excluded")
        for role in ROLES
        for item in _by_status(status, role)
    }
    entity_capabilities = {
        capability for entity in MANIFEST["entities"] for capability in entity["capabilities"]
    }
    entity_commands = {
        command["id"] for entity in MANIFEST["entities"] for command in entity["available_commands"]
    }

    assert set(MANIFEST["capabilities"]) == implemented
    assert set(MANIFEST["commands"]) == implemented_actions
    assert entity_capabilities == implemented
    assert entity_commands == implemented_actions
    assert set(ENTITY_EXAMPLE["capabilities"]) == implemented
    assert set(ENTITY_EXAMPLE["commands"]) == implemented_actions
    assert not unavailable & (
        set(MANIFEST["capabilities"]) | set(MANIFEST["commands"]) | entity_capabilities | entity_commands
    )


def test_sidecar_uses_a_service_entity_and_has_no_device_behaviors() -> None:
    assert not (ROOT / "src" / "behaviors.json").exists()
    assert MANIFEST["entities"] == []
    assert not _by_status("implemented", "conditions")


@pytest.mark.anyio
async def test_contract_identifies_the_runtime_as_a_sidecar() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/contract")
    assert response.status_code == 200
    assert response.json()["kind"] == "sidecar"
    assert response.json()["preset"] == "sidecar-worker"


@pytest.mark.anyio
async def test_quarantine_rejects_configuration_without_retaining_secrets() -> None:
    transport = httpx.ASGITransport(app=app)
    config_id = "capability-catalog-test"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/config", json={"id": config_id, "host": "127.0.0.1", "api_key": "canary-secret"})
        assert response.status_code == 503
        assert response.json()["detail"]["installable"] is False
        assert "canary-secret" not in str((await client.get("/state")).json())


@pytest.mark.anyio
@pytest.mark.parametrize(
    "command",
    ["restart_worker", "analyze_arbitrary_url", "execute_provider_tool"],
)
async def test_unimplemented_and_unsafe_commands_fail_closed(command: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/command",
            json={
                "contract_version": "automation.runtime.command.v1",
                "command": command,
                "target": {"device_id": "llm-vision-service", "config_id": "llm-vision-service"},
                "params": {},
            },
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_implemented"
