from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_climate_widget_package_exposes_complete_control_surface() -> None:
    package = json.loads((ROOT / "experiences/status/package.source.json").read_text())
    widget = package["widgets"][0]
    slots = {slot["id"]: slot for slot in widget["binding_slots"]}

    assert package["identity"]["version"] == "0.3.5"
    assert widget["runtime"] == "sandboxed_bundle"
    assert widget["entry"] == "assets/midea-climate.mjs"
    assert widget["default_column_span"] == 5
    assert widget["permissions"] == ["host.executeCommand"]
    assert set(widget["allowed_commands"]) == {
        "refresh",
        "set_power",
        "set_hvac_mode",
        "set_target_temperature",
        "set_fan_mode",
        "set_swing_mode",
        "set_preset_mode",
    }
    assert set(slots) == {
        "connected", "power", "target", "indoor", "mode", "action",
        "fan-mode", "fan-options", "swing", "swing-options",
        "preset", "preset-options", "outdoor", "fan",
    }
    assert slots["power"]["binding_modes"] == ["read-write"]
    assert slots["target"]["binding_modes"] == ["read-write"]
    assert slots["mode"]["binding_modes"] == ["read-write"]
    assert slots["fan-mode"]["binding_modes"] == ["read-write"]
    assert slots["swing"]["binding_modes"] == ["read-write"]
    assert slots["preset"]["binding_modes"] == ["read-write"]
    bundle_path = ROOT / "experiences/status/assets/midea-climate.mjs"
    assert bundle_path.is_file()
    bundle = bundle_path.read_text()
    assert bundle.count("host.subscribeState(") == 1
    assert "stateSubscriptionParams(bindings)" in bundle
    assert "commandForFanMode" in bundle
    assert "commandForSwingMode" in bundle
    assert "commandForPresetMode" in bundle
    assert "gap: 9px" in bundle
    assert "padding: var(--piphi-widget-space-2, 8px)" in bundle
    assert "width: 44px; height: 44px" in bundle
    assert "padding: 7px 9px" in bundle
    assert "root.scrollHeight + 2" in bundle
    assert "{ slotId: slot.id }" not in bundle


def test_climate_widget_meets_certification_contract() -> None:
    package = json.loads((ROOT / "experiences/status/package.source.json").read_text())
    widget = package["widgets"][0]
    certification = widget["certification"]
    gates = {
        "runtime", "persistence", "binding", "states", "commands",
        "responsive", "themes", "accessibility", "save-reload", "performance",
    }
    assert set(certification["verified_gates"]) == gates
    assert set(certification["evidence"]) == gates

    bundle = (ROOT / widget["entry"].replace("assets/", "experiences/status/assets/")).read_text()
    assert "host.ready(" in bundle
    assert "host.subscribeState(" in bundle
    assert 'event?.kind === "error"' in bundle
    assert "host.executeCommand(" in bundle
    assert "The air conditioner did not respond." in bundle
    assert "@container (max-width: 270px)" in bundle
    assert "prefers-color-scheme: light" in bundle
    assert "prefers-reduced-motion: reduce" in bundle
    assert 'aria-label="Midea climate control"' in bundle
    assert 'aria-label="Target temperature"' in bundle
    assert 'role="alert"' in bundle
    assert 'role="status"' in bundle
