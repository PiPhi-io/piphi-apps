from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


def test_manifest_normalizes_and_validates_in_piphi_core() -> None:
    project_root = Path(__file__).parents[1]
    core_package_root = project_root.parent / "PiPhi-Network-Core" / "src" / "piphi_network_core"
    if not core_package_root.is_dir():
        pytest.skip("PiPhi-Network-Core is not checked out beside the integration")

    sys.path.insert(0, str(core_package_root))
    try:
        from integrations.manifest import normalize_integration_manifest
        from integrations.manifest_validation import validate_manifest_contract

        manifest = json.loads((project_root / "manifest.json").read_text())
        normalized = normalize_integration_manifest(manifest)
        validate_manifest_contract(normalized)
    finally:
        sys.path.remove(str(core_package_root))

    assert normalized["config"]["maximum_instances"] == 1
    assert normalized["ui"]["widget_packages"] == []
    assert normalized["ui"]["experience_packages"] == [
        {
            "registry_id": "io.piphi.sense-energy",
            "version_range": ">=0.1,<1",
            "auto_install": True,
        }
    ]
