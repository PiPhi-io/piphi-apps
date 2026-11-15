from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
BRONZE_RULES = {
    "action-setup", "appropriate-polling", "brands", "common-modules", "config-flow",
    "config-flow-test-coverage", "dependency-transparency", "docs-actions", "docs-conditions",
    "docs-high-level-description", "docs-installation-instructions", "docs-removal-instructions",
    "docs-triggers", "entity-event-setup", "entity-unique-id", "has-entity-name", "runtime-data",
    "test-before-configure", "test-before-setup", "unique-config-entry",
}


def test_bronze_quality_claim_has_complete_auditable_evidence() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    quality = json.loads((ROOT / "quality-scale.yaml").read_text())
    assert manifest["marketplace"]["quality_tier"] == quality["target_tier"] == "bronze"
    assert set(quality["rules"]) == BRONZE_RULES
    for rule in quality["rules"].values():
        assert rule["status"] in {"done", "exempt"}
        if rule["status"] == "exempt":
            assert rule.get("comment")
        else:
            assert rule.get("evidence")
            for evidence in rule["evidence"]:
                assert (ROOT / evidence.split("#", 1)[0]).exists(), evidence
