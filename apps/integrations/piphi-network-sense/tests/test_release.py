from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("check_release", ROOT / "scripts/check_release.py")
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.fixture
def release_root(tmp_path: Path) -> Path:
    for name in ("manifest.json", "pyproject.toml", "src/piphi_network_sense/settings.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_current_release_metadata_matches() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert CHECK.validate_release(f"v{manifest['version']}") == []


def test_runtime_container_uses_a_non_root_persistent_profile() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'USER piphi' in dockerfile
    assert 'VOLUME ["/var/lib/piphi"]' in dockerfile
    assert 'PIPHI_AUTOMATION_LEDGER_PATH=/var/lib/piphi/automation-actions.sqlite3' in dockerfile
    assert 'HEALTHCHECK' in dockerfile


@pytest.mark.parametrize("tag", ["main", "0.1.0", "v0.1.0-rc1", "v01.1.0", "v0.1.0\n"])
def test_invalid_release_tags_are_rejected(tag: str) -> None:
    assert CHECK.validate_release(tag)


def test_version_drift_is_rejected(release_root: Path) -> None:
    errors = CHECK.validate_release("v99.98.97", release_root)
    assert any("manifest.version" in error for error in errors)
    assert any("project.version" in error for error in errors)
    assert any("INTEGRATION_VERSION" in error for error in errors)


@pytest.mark.parametrize("field", ["image", "runtime_image"])
def test_image_destination_drift_is_rejected(release_root: Path, field: str) -> None:
    path = release_root / "manifest.json"
    manifest = json.loads(path.read_text())
    target = manifest if field == "image" else manifest["runtime"]["linux"]["container"]
    target["image"] = "unexpected-owner/sense:latest"
    path.write_text(json.dumps(manifest))
    assert CHECK.validate_release(f"v{manifest['version']}", release_root)
