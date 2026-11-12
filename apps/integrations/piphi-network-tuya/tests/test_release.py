from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_updates_every_version_projection(tmp_path: Path) -> None:
    for relative_path in (
        "pyproject.toml",
        "src/manifest.json",
        "src/piphi_network_tuya/settings.py",
        "experiences/devices/package.source.json",
    ):
        source = ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    copied_script = tmp_path / "scripts" / "release.py"
    copied_script.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "scripts/release.py", copied_script)
    completed = subprocess.run(
        [sys.executable, str(copied_script), "--set-version", "9.8.7"],
        check=True,
        capture_output=True,
        text=True,
    )

    manifest = json.loads((tmp_path / "src/manifest.json").read_text())
    experience = json.loads(
        (tmp_path / "experiences/devices/package.source.json").read_text()
    )
    assert completed.stdout.strip() == "9.8.7"
    assert 'version = "9.8.7"' in (tmp_path / "pyproject.toml").read_text()
    assert 'INTEGRATION_VERSION = "9.8.7"' in (
        tmp_path / "src/piphi_network_tuya/settings.py"
    ).read_text()
    assert manifest["version"] == "9.8.7"
    assert manifest["image"].endswith(":9.8.7")
    assert manifest["runtime"]["linux"]["container"]["image"] == manifest["image"]
    assert experience["identity"]["version"] == "9.8.7"


def test_release_pipeline_enforces_supply_chain_gates() -> None:
    release = (ROOT / ".github/workflows/release.yml").read_text()

    assert "Validate bumped release contract" in release
    assert "provenance: mode=max" in release
    assert "sbom: true" in release
    assert "SHA256SUMS" in release
    assert "tuya-experience-${{ steps.version.outputs.version }}.json" in release
