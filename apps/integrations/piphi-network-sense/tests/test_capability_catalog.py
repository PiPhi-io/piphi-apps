from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_capability_catalog_accounts_for_manifest_and_simulator_profiles() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads(
        (ROOT / "docs" / "capability-catalog.json").read_text(encoding="utf-8")
    )
    rows = {row["id"]: row for row in catalog["capabilities"]}
    profiles = {profile["id"]: profile for profile in catalog["entity_profiles"]}

    assert catalog["integration_id"] == manifest["id"]
    assert catalog["catalog_version"] == manifest["version"]
    assert set(manifest["capabilities"]) <= rows.keys()
    assert all(
        rows[capability]["status"] == "implemented"
        for capability in manifest["capabilities"]
    )
    assert set(manifest["commands"]) == {
        row["id"] for row in catalog["commands"] if row["status"] == "implemented"
    }
    assert all(profile["simulated"] is True for profile in profiles.values())
    assert set(profiles["sense-monitor"]["capabilities"]) == set(
        manifest["entities"][0]["capabilities"]
    )
    assert set(profiles["detected-appliance"]["capabilities"]) == {
        "device_power_w",
        "device_on",
        "device_daily_energy_kwh",
    }


def test_release_readiness_keeps_hardware_validation_honest() -> None:
    catalog = json.loads(
        (ROOT / "docs" / "capability-catalog.json").read_text(encoding="utf-8")
    )

    assert catalog["completion"] == {
        "status": "release_candidate",
        "automated_runtime_validation": "passed",
        "simulator_validation": "passed",
        "physical_account_validation": "pending",
        "widget_package_migration": "passed",
    }
    assert catalog["simulator"] == {
        "repository": "piphi-integration-simulators",
        "scenario": "sense",
        "presets": ["balanced", "high_load", "solar_export", "overnight", "offline"],
        "uses_integration_experience_package": True,
    }
