from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_camera_service_uses_a_core_supported_marketplace_category() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())

    assert manifest["marketplace"]["category"] == "camera"
    assert manifest["marketplace"]["display_name"] == "Camera Media Service"
    assert manifest["marketplace"]["discovery_methods"] == []
