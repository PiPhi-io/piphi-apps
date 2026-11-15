from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_manifest_declares_linux_oci_and_windows_native_python_proxy() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    app = json.loads((ROOT / "piphi-app.json").read_text())
    project = (ROOT / "pyproject.toml").read_text()
    assert manifest["platforms"] == ["linux", "windows"]
    assert manifest["runtime"]["linux"]["type"] == "container"
    windows = manifest["runtime"]["windows"]
    assert windows["type"] == "proxy"
    assert windows["proxy"]["process"] == {
        "kind": "python_executable",
        "command": "piphi_ble_gateway_sidecar",
        "supervisor": "chief",
    }
    assert 'piphi_ble_gateway_sidecar = "piphi_ble_gateway_sidecar.main:main"' in project
    assert app["packages"][0]["artifact"]["platforms"] == ["linux/amd64", "linux/arm64"]
    assert app["ci"]["enforcement"] == "full"


def test_versions_and_images_are_consistent() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    app = json.loads((ROOT / "piphi-app.json").read_text())
    assert manifest["version"] == app["packages"][0]["version"] == "0.2.0"
    assert manifest["image"] == manifest["runtime"]["linux"]["container"]["image"]
    assert manifest["image"].endswith(":0.2.0")
