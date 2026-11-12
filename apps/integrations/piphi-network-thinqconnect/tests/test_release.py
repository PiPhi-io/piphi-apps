from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_release_updates_every_version_projection(tmp_path) -> None:
    for relative_path in (
        "pyproject.toml",
        "src/manifest.json",
        "widgets/thinqconnect-overview/package.json",
        "widgets/thinqconnect-overview/package-lock.json",
        "widgets/thinqconnect-overview/widget.manifest.json",
    ):
        source = ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/release.py"),
            "--repo-root",
            str(tmp_path),
            "--set-version",
            "9.8.7",
            "--docker-image",
            "piphinetwork/lg-thinq-connect",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = _json(tmp_path / "src/manifest.json")
    widget_package = _json(tmp_path / "widgets/thinqconnect-overview/package.json")
    widget_lock = _json(tmp_path / "widgets/thinqconnect-overview/package-lock.json")
    widget_manifest = _json(tmp_path / "widgets/thinqconnect-overview/widget.manifest.json")
    assert completed.stdout.strip() == "9.8.7"
    assert 'version = "9.8.7"' in (tmp_path / "pyproject.toml").read_text()
    assert manifest["version"] == "9.8.7"
    assert manifest["runtime"]["linux"]["container"]["image"].endswith(":9.8.7")
    assert manifest["ui"]["widget_packages"][0]["version"] == "9.8.7"
    assert widget_package["version"] == "9.8.7"
    assert widget_lock["version"] == "9.8.7"
    assert widget_lock["packages"][""]["version"] == "9.8.7"
    assert widget_manifest["version"] == "9.8.7"


def test_release_pipeline_enforces_widget_and_supply_chain_gates() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text()

    for command in ("npm run build", "npm test", "npm run validate", "npm run conformance"):
        assert command in ci
        assert command in release
    assert "provenance: mode=max" in release
    assert "sbom: true" in release
    assert "SHA256SUMS" in release
