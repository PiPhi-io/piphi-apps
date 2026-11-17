from __future__ import annotations

import json
from pathlib import Path

from piphi_wyze_camera_service.main import app
from piphi_wyze_camera_service.settings import INTEGRATION_ID, INTEGRATION_VERSION

ROOT = Path(__file__).parents[1]


def test_runtime_routes_match_manifest_contract() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    routes = set(app.openapi()["paths"])

    assert manifest["id"] == INTEGRATION_ID
    assert manifest["version"] == INTEGRATION_VERSION
    assert set(manifest["api"]["endpoints"].values()) <= routes
    assert manifest["provides"]["services"][0]["capabilities"] == ["camera.bridge.wyze.v1"]


def test_managed_service_uses_core_allocated_primary_port() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    container = manifest["runtime"]["linux"]["container"]

    assert manifest["onboarding"] == {"mode": "service"}
    assert manifest["runtime_contract"] == {
        "version": 1,
        "port_binding": "core_allocated",
        "port_env": "PORT",
    }
    assert container["ports"][0] == {"container": 8090}
    assert container["ports"][1] == {
        "container": 8554,
        "protocol": "tcp",
    }


def test_capability_catalog_does_not_advertise_deferred_features() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    catalog = json.loads((ROOT / "docs" / "capability-catalog.json").read_text())
    implemented = {
        item["id"] for item in catalog["capabilities"] if item["status"] == "implemented"
    }

    assert implemented == set(manifest["provides"]["services"][0]["capabilities"])
    assert manifest["capabilities"] == {}


def test_exact_container_pins_the_audited_wyze_dependency() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    dockerfile = (ROOT / "Dockerfile").read_text()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
    digest = "sha256:af2d638a6d6d52e15ddcfb711e5b905e484b1f519986ad33b9be562b6277b987"

    assert manifest["metadata"]["upstream"]["version"] == "2.10.3"
    assert f"mrlt8/wyze-bridge:2.10.3@{digest}" in dockerfile
    assert digest in notices
    assert manifest["marketplace"]["compatibility"] == []
