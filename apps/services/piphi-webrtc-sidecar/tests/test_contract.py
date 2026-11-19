from __future__ import annotations

import json
from pathlib import Path

from piphi_webrtc_sidecar.contract import REQUIRED_ENDPOINTS
from piphi_webrtc_sidecar.main import app

ROOT = Path(__file__).parents[1]


def test_runtime_implements_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    for path in [
        "/health",
        "/diagnostics",
        "/contract",
        "/v1/camera-media/sessions",
        "/v1/camera-media/sessions/{session_id}",
        "/v1/camera-media/sessions/{session_id}/keepalive",
        "/v1/camera-media/status",
        "/v1/analysis-media",
        "/v1/analysis-media/{media_ref}",
    ]:
        assert path in routes

    for legacy_device_path in [
        "/discover",
        "/config",
        "/config/sync",
        "/deconfigure",
        "/ui-config",
        "/entities",
        "/state",
        "/events",
        "/command",
        "/v1/cameras/{config_id}/webrtc",
        "/v1/cameras/{config_id}/snapshot",
    ]:
        assert legacy_device_path not in routes

    assert REQUIRED_ENDPOINTS == [
        "health",
        "camera_media_status",
        "camera_media_sessions",
        "camera_media_session_keepalive",
        "analysis_media_issue",
        "analysis_media",
    ]


def test_manifest_declares_a_shared_zero_setup_camera_media_service() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())

    assert manifest["id"] == "piphi.service.webrtc-sidecar"
    assert manifest["name"] == "PiPhi Camera Media Service"
    assert manifest["kind"] == "platform_service"
    assert manifest["deployment_mode"] == "sidecar"
    assert manifest["onboarding"] == {"mode": "service"}
    assert "discovery" not in manifest["runtime"]["linux"]
    assert "config" not in manifest
    assert "identity" not in manifest
    assert "entities" not in manifest
    assert "commands" not in manifest
    assert manifest.get("capabilities") == {}
    assert manifest["provides"]["services"] == [
        {
            "id": "piphi.service.webrtc-sidecar",
            "kind": "platform_service",
            "capabilities": ["camera.media.v1", "camera.analysis-media.v1"],
            "shared": True,
        }
    ]
    assert "discover" not in manifest["api"]["endpoints"]
    assert "config" not in manifest["api"]["endpoints"]
    assert "entities" not in manifest["api"]["endpoints"]


def test_package_ci_requires_the_real_pinned_container_smoke() -> None:
    app_metadata = json.loads((ROOT / "piphi-app.json").read_text())

    assert (
        "pdm run python scripts/smoke_container.py --build --image piphi-webrtc-sidecar:ci-smoke"
    ) in app_metadata["ci"]["commands"]


def test_image_declares_release_provenance_and_non_root_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert 'org.opencontainers.image.source="${SOURCE_REPOSITORY}"' in dockerfile
    assert 'org.opencontainers.image.revision="${SOURCE_REVISION}"' in dockerfile
    assert 'org.opencontainers.image.version="${RELEASE_VERSION}"' in dockerfile
    assert "USER piphi" in dockerfile
