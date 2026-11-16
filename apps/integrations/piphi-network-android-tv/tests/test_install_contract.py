from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
APPS = ROOT.parents[1]
PARENT_MANIFEST = json.loads((ROOT / "manifest.json").read_text())
SIDECAR_ROOT = APPS / "services" / "piphi-android-adb-sidecar"
SIDECAR_MANIFEST = json.loads((SIDECAR_ROOT / "manifest.json").read_text())
SIDECAR_PACKAGE = json.loads((SIDECAR_ROOT / "piphi-app.json").read_text())


def test_parent_auto_installs_compatible_adb_sidecar() -> None:
    assert PARENT_MANIFEST["requires"]["services"] == [
        {
            "id": "piphi-android-adb-sidecar",
            "kind": "platform_service",
            "version_range": ">=0.3.0-rc.1,<0.4.0",
            "recommended_version": "0.3.0-rc.1",
            "required": True,
            "shared": True,
            "auto_install": True,
            "reason": (
                "Owns authenticated network ADB sessions, opaque target leases, bounded "
                "command queues, and strict property and key allow-lists."
            ),
        }
    ]
    package = SIDECAR_PACKAGE["packages"][0]
    assert package["id"] == "piphi-android-adb-sidecar"
    assert package["type"] == "platform_service"
    assert package["version"] == "0.3.0-rc.1"


def test_managed_adb_sidecar_is_internal_and_uses_injected_authentication() -> None:
    parent = PARENT_MANIFEST["runtime"]["linux"]["container"]
    sidecar = SIDECAR_MANIFEST["runtime"]["linux"]["container"]

    assert parent["environment"]["PIPHI_ENV"] == "production"
    assert parent["environment"]["PIPHI_ANDROID_ADB_SIDECAR_URL"] == (
        "http://piphi-android-adb-sidecar:4213"
    )
    assert sidecar["ports"] == [{"container": 4213}]
    assert "PIPHI_ANDROID_ADB_SIDECAR_TOKEN" not in parent["environment"]
    assert "PIPHI_INTEGRATION_INTERNAL_TOKEN" not in parent["environment"]
    assert "PIPHI_ANDROID_ADB_SIDECAR_TOKEN" not in sidecar["environment"]
    assert "PIPHI_INTEGRATION_INTERNAL_TOKEN" not in sidecar["environment"]


def test_parent_and_sidecar_release_metadata_are_consistent() -> None:
    assert PARENT_MANIFEST["version"] == "0.3.0-rc.1"
    assert PARENT_MANIFEST["image"].endswith(":0.3.0-rc.1")
    assert SIDECAR_MANIFEST["version"] == "0.3.0-rc.1"
    assert SIDECAR_MANIFEST["image"].endswith(":0.3.0-rc.1")
