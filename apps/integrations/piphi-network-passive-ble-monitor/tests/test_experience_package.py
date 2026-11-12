from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MANIFEST = json.loads((ROOT / "manifest.json").read_text())
PACKAGE = json.loads((ROOT / "experiences" / "status" / "package.source.json").read_text())


def test_experience_matches_the_runtime_contract() -> None:
    assert PACKAGE["identity"] == {
        "publisher_id": "io.piphi",
        "package_id": "passive-ble-monitor-status",
        "version": "0.2.3",
    }
    assert PACKAGE["owning_integration_id"] == MANIFEST["id"]

    widget = PACKAGE["widgets"][0]
    requirements = {
        capability
        for slot in widget["binding_slots"]
        for capability in slot["capability_requirements"]
    }
    assert requirements == {
        "temperature_c",
        "humidity_percent",
        "battery_percent",
        "rssi_dbm",
    }
    assert "connected" in MANIFEST["capabilities"]
    assert all(slot["binding_modes"] == ["read"] for slot in widget["binding_slots"])
    assert {item["slot_id"] for item in widget["recipe"]["items"]} == {
        slot["id"] for slot in widget["binding_slots"]
    }


def test_experience_preserves_widget_identity_for_in_place_upgrades() -> None:
    widget = PACKAGE["widgets"][0]
    assert widget["id"] == "connection-status"
    assert widget["default_column_span"] == 4
    assert widget["default_row_span"] == 2
