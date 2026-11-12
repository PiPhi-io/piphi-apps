from __future__ import annotations

import json
import importlib.util
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
        normalized = normalize_integration_manifest(json.loads((project_root / "manifest.json").read_text()))
        validate_manifest_contract(normalized)
    finally:
        sys.path.remove(str(core_package_root))

    assert normalized["config"]["maximum_instances"] == 1
    assert normalized["ui"]["widget_packages"] == []
    assert normalized["ui"]["experience_packages"] == [{
        "registry_id": "io.piphi.solaredge-solar-energy",
        "version_range": ">=0.1,<1",
        "auto_install": True,
    }]


def test_behaviors_parse_and_validate_in_piphi_core() -> None:
    project_root = Path(__file__).parents[1]
    core_package_root = project_root.parent / "PiPhi-Network-Core" / "src" / "piphi_network_core"
    if not core_package_root.is_dir():
        pytest.skip("PiPhi-Network-Core is not checked out beside the integration")
    behavior_root = core_package_root / "integrations" / "behaviors"

    def load_module(name: str, filename: str):
        spec = importlib.util.spec_from_file_location(name, behavior_root / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    sys.path.insert(0, str(core_package_root))
    try:
        contract = load_module("core_behavior_contract", "contract.py")
        schema = load_module("core_behavior_schema", "schema.py")
        payload = json.loads((project_root / "src" / "behaviors.json").read_text())
        parsed = schema.BehaviorSchemaDocument.model_validate(payload)
        errors = contract.validate_behavior_contract(payload)
    finally:
        sys.path.remove(str(core_package_root))

    assert parsed.behavior_schema_version == "integration.behaviors.v2"
    assert errors == []
