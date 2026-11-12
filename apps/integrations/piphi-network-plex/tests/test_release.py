from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_release import validate_release


def test_release_manifest_registry_and_bundles_are_consistent():
    version = json.loads((ROOT / "manifest.json").read_text())["version"]
    validate_release(ROOT, f"v{version}")


def test_release_ref_cannot_publish_a_different_version():
    with pytest.raises(ValueError, match="tag matching"):
        validate_release(ROOT, "main")


@pytest.fixture
def release_tree(tmp_path):
    for name in ("manifest.json", "pyproject.toml"):
        shutil.copy(ROOT / name, tmp_path / name)
    for name in ("registry", "widgets"):
        shutil.copytree(ROOT / name, tmp_path / name)
    return tmp_path


def test_release_rejects_registry_drift(release_tree):
    path = release_tree / "registry/plex.json"
    entry = json.loads(path.read_text())
    entry["version"] = "9.9.9"
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match="manifest-derived"):
        validate_release(release_tree)


def test_release_rejects_modified_widget_bundle(release_tree):
    path = release_tree / "widgets/recently-added/dist/widget.js"
    path.write_bytes(path.read_bytes() + b"\n// modified")
    with pytest.raises(ValueError, match="integrity mismatch"):
        validate_release(release_tree)
