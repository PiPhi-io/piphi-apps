from __future__ import annotations

import json
from pathlib import Path

import tomllib

from piphi_camera_stream.settings import INTEGRATION_VERSION


ROOT = Path(__file__).parents[1]


def test_release_metadata_uses_one_version() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    package_contract = json.loads((ROOT / "package-contract.json").read_text())
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        project_version = tomllib.load(pyproject_file)["project"]["version"]

    assert manifest["version"] == "0.1.4"
    assert manifest["version"] == package_contract["version"]
    assert manifest["version"] == project_version
    assert manifest["version"] == INTEGRATION_VERSION
    assert manifest["image"].endswith(f":{manifest['version']}")
    assert manifest["runtime"]["linux"]["container"]["image"] == manifest["image"]
