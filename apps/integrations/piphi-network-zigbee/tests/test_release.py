from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_updates_all_version_and_image_projections(tmp_path: Path) -> None:
    for relative_path in (
        "pyproject.toml",
        "src/manifest.json",
        "src/piphi_network_zigbee/settings.py",
        "experiences/devices/package.source.json",
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
            "piphinetwork/zigbee-integration",
        ],
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
    assert manifest["version"] == "9.8.7"
    assert manifest["image"] == "piphinetwork/zigbee-integration:9.8.7"
    assert manifest["runtime"]["linux"]["container"]["image"].endswith(":9.8.7")
    assert experience["identity"]["version"] == "9.8.7"
    assert 'INTEGRATION_VERSION = "9.8.7"' in (
        tmp_path / "src/piphi_network_zigbee/settings.py"
    ).read_text()


def test_release_pipeline_enforces_supply_chain_gates() -> None:
    release = (ROOT.parents[2] / ".github/workflows/release-app.yml").read_text()

    assert "docker/build-push-action@v6" in release
    assert "provenance: mode=max" in release
    assert "sbom: true" in release
    assert "actions/attest-build-provenance@v2" in release
    assert "release-evidence.json" in release
    assert "registry-proposal.json" in release
    assert "softprops/action-gh-release@v2" in release
