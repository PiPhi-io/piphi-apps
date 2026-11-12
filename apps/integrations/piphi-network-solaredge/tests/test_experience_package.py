from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "experiences" / "solar-energy" / "package.source.json"
_builder_spec = importlib.util.spec_from_file_location(
    "solaredge_experience_builder", ROOT / "scripts" / "build_experience.py"
)
assert _builder_spec is not None and _builder_spec.loader is not None
_builder = importlib.util.module_from_spec(_builder_spec)
sys.modules[_builder_spec.name] = _builder
_builder_spec.loader.exec_module(_builder)
build = _builder.build
ALLOWED_THEME_TOKENS = {
    "--piphi-experience-accent", "--piphi-experience-surface",
    "--piphi-experience-tile-surface", "--piphi-experience-tile-border",
    "--piphi-experience-shadow", "--piphi-experience-tile-shadow",
    "--piphi-experience-radius", "--piphi-experience-gap",
    "--piphi-experience-temperature-accent", "--piphi-experience-humidity-accent",
    "--piphi-experience-air-quality-accent", "--piphi-experience-energy-accent",
}


def _source() -> dict:
    return json.loads(SOURCE.read_text())


def test_one_integration_owned_package_contains_both_widgets() -> None:
    source = _source()
    assert source["origin"] == "integration"
    assert source["owning_integration_id"] == "piphi-network-solaredge"
    assert [widget["id"] for widget in source["widgets"]] == ["energy-flow", "production-summary"]
    assert all(widget["runtime"] == "declarative" for widget in source["widgets"])
    assert all(widget["presentation"]["shell"] == "core" for widget in source["widgets"])
    assert all(widget["permissions"] == [] if "permissions" in widget else True for widget in source["widgets"])
    assert source["identity"]["version"] == "0.1.5"
    assert all(widget["default_row_span"] == 2 for widget in source["widgets"])
    assert source["widgets"][1]["default_column_span"] == 6
    assert [item["label"] for item in source["widgets"][1]["recipe"]["items"]] == [
        "Today", "Month", "Year", "Lifetime",
    ]


def test_bindings_are_source_scoped_fresh_and_history_capable() -> None:
    source = _source()
    manifest_capabilities = set(json.loads((ROOT / "manifest.json").read_text())["capabilities"])
    for widget in source["widgets"]:
        slots = {slot["id"]: slot for slot in widget["binding_slots"]}
        assert slots
        for slot in slots.values():
            assert slot["compatible_integration_ids"] == ["piphi-network-solaredge"]
            assert 5 <= slot["data_delivery"]["stale_after_seconds"] <= 604800
            assert set(slot["capability_requirements"]) <= manifest_capabilities
        targets = {target["binding_slot_id"]: target for target in widget["interaction_targets"] if target["kind"] == "binding"}
        assert targets.keys() == slots.keys()
        assert all("more-info" in target["allowed_actions"] for target in targets.values())
        assert all("history" in target["allowed_actions"] for target in targets.values() if target["binding_slot_id"] != "connectivity")


def test_declarative_content_has_accessible_labels_and_freshness() -> None:
    for widget in _source()["widgets"]:
        assert widget["name"] and widget["description"]
        for target in widget["interaction_targets"]:
            assert target["label"].strip()
        items = []
        for item in widget["recipe"]["items"]:
            items.extend(item.get("items", [item]))
        for item in items:
            if item["type"] in {"metric", "status", "progress"}:
                assert item["label"].strip()
                assert item["action"]["label"].strip()
        assert any(item.get("show_freshness") for item in items)


def test_themes_use_only_core_allowlisted_tokens() -> None:
    source = _source()
    stylesheets = {theme["stylesheet"] for widget in source["widgets"] for theme in widget["themes"]}
    assert stylesheets == {"themes/solaredge.css", "themes/quiet.css"}
    for stylesheet in stylesheets:
        css = (SOURCE.parent / stylesheet).read_text()
        assert css.strip().startswith(":root {")
        assert "@import" not in css and "url(" not in css
        tokens = {line.split(":", 1)[0].strip() for line in css.splitlines() if line.strip().startswith("--")}
        assert tokens and tokens <= ALLOWED_THEME_TOKENS
        assert "--piphi-experience-tile-border: transparent" in css
        assert "--piphi-experience-gap: 8px" in css
    assert "--piphi-experience-surface: transparent" in (
        SOURCE.parent / "themes/solaredge.css"
    ).read_text()


def test_signed_build_is_deterministic_and_contains_shared_assets_once(tmp_path: Path) -> None:
    first_archive, first_manifest = build(tmp_path / "first", check=True, env_name="unused", key_id="test-key")
    second_archive, _ = build(tmp_path / "second", check=True, env_name="unused", key_id="test-key")
    # Ephemeral signatures differ, while the deterministic package bytes do not.
    assert first_archive.read_bytes() == second_archive.read_bytes()
    manifest = json.loads(first_manifest.read_text())
    assert manifest["artifact"]["digest"] == f"sha256:{hashlib.sha256(first_archive.read_bytes()).hexdigest()}"
    with ZipFile(first_archive) as package:
        assert package.namelist() == ["package.source.json", "themes/quiet.css", "themes/solaredge.css"]


def test_built_manifest_validates_against_checked_out_core_contract(tmp_path: Path) -> None:
    contract_path = ROOT.parent / "PiPhi-Network-Core" / "src" / "piphi_network_core" / "widgets" / "package_contract.py"
    if not contract_path.is_file():
        pytest.skip("PiPhi-Network-Core is not checked out beside the integration")
    spec = importlib.util.spec_from_file_location("solaredge_core_widget_contract", contract_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _, manifest_path = build(tmp_path, check=True, env_name="unused", key_id="test-key")
    parsed = module.InstalledWidgetPackageManifest.model_validate_json(manifest_path.read_text())
    assert len(parsed.widgets) == 2
