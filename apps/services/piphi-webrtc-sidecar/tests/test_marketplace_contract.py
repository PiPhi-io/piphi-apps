from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_camera_service_uses_a_core_supported_marketplace_category() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())

    assert manifest["marketplace"]["category"] == "camera"
    assert manifest["marketplace"]["display_name"] == "Camera Media Service"
    assert manifest["marketplace"]["discovery_methods"] == []


def test_exact_container_pins_the_qualified_go2rtc_binary() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    dockerfile = (ROOT / "Dockerfile").read_text()
    digest = "sha256:e098de5c2f8040dc3d4784ed2d5cfdac3b0979f9349afe587ef6a670a14b9f4d"

    assert manifest["metadata"]["upstream"]["version"] == "1.9.15"
    assert f"ghcr.io/alexxit/go2rtc:1.9.15@{digest}" in dockerfile
    assert "wyze-p2p" not in manifest["marketplace"]["protocols"]
