from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
APPS = ROOT.parents[1]
PARENT_MANIFEST = json.loads((ROOT / "manifest.json").read_text())
SIDECAR_ROOT = APPS / "services" / "piphi-modbus-rtu-sidecar"
SIDECAR_MANIFEST = json.loads((SIDECAR_ROOT / "manifest.json").read_text())
SIDECAR_PACKAGE = json.loads((SIDECAR_ROOT / "piphi-app.json").read_text())


def test_parent_auto_installs_compatible_rtu_sidecar() -> None:
    assert PARENT_MANIFEST["requires"]["services"] == [
        {
            "id": "piphi-modbus-rtu-sidecar",
            "kind": "platform_service",
            "version_range": ">=0.2.1,<0.3.0",
            "recommended_version": "0.2.1",
            "required": True,
            "shared": True,
            "auto_install": True,
            "reason": (
                "Owns authenticated serial access, RTU framing, bounded request "
                "arbitration, and read/write execution for profile-declared RTU points."
            ),
        }
    ]
    package = SIDECAR_PACKAGE["packages"][0]
    assert package["id"] == "piphi-modbus-rtu-sidecar"
    assert package["type"] == "platform_service"
    assert package["version"] == "0.2.1"


def test_managed_rtu_sidecar_is_internal_authenticated_and_serial_only() -> None:
    parent_container = PARENT_MANIFEST["runtime"]["linux"]["container"]
    sidecar_container = SIDECAR_MANIFEST["runtime"]["linux"]["container"]

    assert parent_container["environment"]["PIPHI_ENV"] == "production"
    assert parent_container["environment"]["PIPHI_MODBUS_SIDECAR_URL"] == (
        "http://piphi-modbus-rtu-sidecar:4212"
    )
    assert sidecar_container["environment"]["PIPHI_ENV"] == "production"
    assert sidecar_container["ports"] == [{"container": 4212}]
    assert sidecar_container["devices"] == [
        {
            "host": "/dev/serial",
            "container": "/dev/serial",
            "permissions": "rwm",
        }
    ]
    assert "PIPHI_MODBUS_SIDECAR_TOKEN" not in sidecar_container["environment"]
    assert "PIPHI_INTEGRATION_INTERNAL_TOKEN" not in sidecar_container["environment"]


def test_coordinated_patch_versions_and_images_are_consistent() -> None:
    assert PARENT_MANIFEST["version"] == "0.3.1"
    assert PARENT_MANIFEST["image"].endswith(":0.3.1")
    assert SIDECAR_MANIFEST["version"] == "0.2.1"
    assert SIDECAR_MANIFEST["image"].endswith(":0.2.1")
