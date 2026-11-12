from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_behaviors_and_catalog_agree() -> None:
    manifest = json.loads((ROOT / "src/manifest.json").read_text())
    behaviors = json.loads((ROOT / "src/behaviors.json").read_text())
    catalog = json.loads((ROOT / "capability-catalog.json").read_text())

    advertised = set(manifest["capabilities"])
    behavior_capabilities = set(behaviors["devices"][0]["capabilities"])
    implemented = {
        capability
        for row in catalog["rows"]
        if row["status"] == "implemented"
        for capability in row["capabilities"]
    }
    assert implemented <= advertised
    assert behavior_capabilities <= advertised
    assert manifest["marketplace"]["governance"]["publication_status"] == "draft"
    assert manifest["marketplace"]["governance"]["rollout_percent"] == 0
    assert manifest["marketplace"]["quality_tier"] == "unrated"


def test_secret_is_not_declared_as_state_or_widget_capability() -> None:
    manifest = json.loads((ROOT / "src/manifest.json").read_text())
    widget = json.loads((ROOT / "widgets/steam-activity/widget.manifest.json").read_text())
    assert "web_api_key" not in manifest["capabilities"]
    assert "web_api_key" not in widget["capability_requirements"]
    assert widget["security"]["permissions"] == []
    assert widget["security"]["csp"]["connect_src"] == []
