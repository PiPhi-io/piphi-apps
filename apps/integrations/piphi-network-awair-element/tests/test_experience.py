from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_air_quality_experience_matches_runtime_manifest() -> None:
    manifest = json.loads((ROOT / "src/manifest.json").read_text(encoding="utf-8"))
    source = json.loads(
        (ROOT / "experiences/air-quality/package.source.json").read_text(
            encoding="utf-8"
        )
    )
    identity = source["identity"]
    package_id = f"{identity['publisher_id']}.{identity['package_id']}"
    references = manifest["ui"]["experience_packages"]

    assert source["owning_integration_id"] == manifest["id"]
    assert identity["version"] == manifest["version"]
    assert references == [
        {
            "registry_id": package_id,
            "version_range": ">=0.1,<1",
            "auto_install": True,
        }
    ]

    (widget,) = source["widgets"]
    assert widget["runtime"] == "declarative"
    assert widget["presentation"]["shell"] == "core"
    certification = widget["certification"]
    assert certification["schema_version"] == "1"
    assert set(certification["verified_gates"]) == {
        "runtime", "persistence", "binding", "states", "responsive",
        "themes", "accessibility", "save-reload", "performance",
    }
    assert set(certification["evidence"]) == set(certification["verified_gates"])
    assert certification["evidence"]["binding"] == [
        "repo:tests/test_experience.py::test_air_quality_experience_matches_runtime_manifest"
    ]
    slots = {slot["id"]: slot for slot in widget["binding_slots"]}
    assert len(slots) == len(widget["binding_slots"])
    assert sum(slot["required"] for slot in slots.values()) == 1
    assert all(slot["binding_modes"] == ["read"] for slot in slots.values())
    manifest_semantics = {
        capability["semantic_type"]
        for capability in manifest["capabilities"].values()
        if capability.get("semantic_type")
    }
    for slot in slots.values():
        assert slot["value_kinds"] == ["numeric"]
        assert set(slot["semantic_types"]) <= manifest_semantics
        assert "compatible_integration_ids" not in slot
        assert "capability_requirements" not in slot

    recipe_slots = {item["slot_id"] for item in widget["recipe"]["items"]}
    assert recipe_slots == set(slots)
    assert {
        target["binding_slot_id"]
        for target in widget["interaction_targets"]
        if target["kind"] == "binding"
    } == set(slots)
    assert not recipe_slots & {"voc_h2_raw", "voc_ethanol_raw", "co2_est_baseline"}


def test_release_container_uses_current_sdk_and_non_root_persistence() -> None:
    source = (ROOT / "Dockerfile").read_text()
    assert "FROM python:3.12-slim@sha256:" in source
    assert "pip install --no-cache-dir --require-hashes" in source
    assert "USER 10001:10001" in source
    assert 'VOLUME ["/var/lib/piphi"]' in source
    assert "chmod -R a-w /app" in source
    assert "HEALTHCHECK" in source
    ignored = set((ROOT / ".dockerignore").read_text().splitlines())
    assert {".git", ".venv", "__pycache__", "*.pyc", "tests"} <= ignored
