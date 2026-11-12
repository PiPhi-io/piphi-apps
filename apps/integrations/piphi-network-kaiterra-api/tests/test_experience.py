from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_air_quality_experience_tracks_manifest_capabilities() -> None:
    manifest = json.loads((ROOT / "src/manifest.json").read_text(encoding="utf-8"))
    package = json.loads(
        (ROOT / "experiences/air-quality/package.source.json").read_text(
            encoding="utf-8"
        )
    )
    identity = package["identity"]
    assert package["owning_integration_id"] == manifest["id"]
    assert identity["version"] == manifest["version"]
    assert manifest["ui"]["experience_packages"][0]["registry_id"] == (
        f"{identity['publisher_id']}.{identity['package_id']}"
    )
    assert manifest["ui"]["experience_packages"][0]["auto_install"] is True

    (widget,) = package["widgets"]
    assert widget["runtime"] == "declarative"
    assert widget["presentation"]["shell"] == "core"
    slots = {slot["id"]: slot for slot in widget["binding_slots"]}
    assert set(slots) == {"co2", "pm25", "tvoc", "temperature", "humidity", "ozone"}
    assert sum(slot["required"] for slot in slots.values()) == 1
    assert {item["slot_id"] for item in widget["recipe"]["items"]} == set(slots)
    assert {
        target["binding_slot_id"]
        for target in widget["interaction_targets"]
        if target["kind"] == "binding"
    } == set(slots)
    for slot in slots.values():
        assert slot["binding_modes"] == ["read"]
        assert slot["compatible_integration_ids"] == [manifest["id"]]
        assert set(slot["capability_requirements"]) <= set(manifest["capabilities"])
