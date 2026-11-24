from __future__ import annotations

import json
import tomllib
from pathlib import Path

from piphi_network_kaiterra_api.contract import CAPABILITIES, COMMANDS
from piphi_network_kaiterra_api.settings import INTEGRATION_VERSION
from piphi_network_kaiterra_api.routes.commands import automation_registry

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_capability_catalog_is_unique_and_synchronized() -> None:
    catalog = _json("capability-catalog.json")
    manifest = _json("src/manifest.json")
    behaviors = _json("src/behaviors.json")
    entries = catalog["entries"]
    assert len({entry["id"] for entry in entries}) == len(entries)
    implemented_capabilities = {
        capability
        for entry in entries if entry["status"] == "implemented"
        for capability in entry.get("capabilities", [])
    }
    implemented_actions = {
        action
        for entry in entries if entry["status"] == "implemented"
        for action in entry.get("actions", [])
    }
    implemented_events = {
        event
        for entry in entries if entry["status"] == "implemented"
        for event in entry.get("events", [])
    }
    assert implemented_capabilities <= set(CAPABILITIES)
    assert implemented_actions == set(COMMANDS)
    assert implemented_events == {
        item["event_type"] for item in automation_registry.contract_snapshot()["events"]
    }
    assert set(CAPABILITIES) == set(manifest["capabilities"])
    assert set(COMMANDS) == set(manifest["commands"])
    assert set(behaviors["devices"][0]["capabilities"]) == set(CAPABILITIES)
    assert "pir" not in manifest["capabilities"]
    assert manifest["entities"] == []


def test_minimum_patch_version_is_synchronized() -> None:
    manifest = _json("src/manifest.json")
    app = _json("piphi-app.json")
    experience = _json("experiences/air-quality/package.source.json")
    assert INTEGRATION_VERSION == "0.1.6"
    assert manifest["version"] == INTEGRATION_VERSION
    assert app["packages"][0]["version"] == INTEGRATION_VERSION
    assert experience["identity"]["version"] == INTEGRATION_VERSION
    assert manifest["runtime"]["linux"]["container"]["image"].endswith(f":{INTEGRATION_VERSION}")


def test_container_contract_is_locked_non_root_and_read_only() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    manifest = _json("src/manifest.json")
    assert dockerfile.count("python:3.12-slim@sha256:") == 2
    assert "--require-hashes" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert manifest["runtime"]["linux"]["container"]["read_only"] is True


def test_wheel_declares_runtime_contract_artifacts() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    included = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert set(included.values()) == {
        "piphi_network_kaiterra_api/behaviors.json",
        "piphi_network_kaiterra_api/manifest.json",
        "piphi_network_kaiterra_api/capability-catalog.json",
    }
