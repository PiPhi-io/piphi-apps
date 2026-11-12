from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _manifest() -> dict:
    return json.loads((ROOT / "manifest.json").read_text())


def test_rtsp_camera_uses_manual_setup_without_device_discovery() -> None:
    manifest = _manifest()

    assert manifest["onboarding"] == {"mode": "manual"}
    assert manifest["marketplace"]["category"] == "security"
    assert "discovery" not in manifest["runtime"]["linux"]
    assert "discover" not in manifest["api"]["endpoints"]


def test_rtsp_camera_auto_installs_the_shared_webrtc_service() -> None:
    manifest = _manifest()

    assert manifest["requires"]["services"] == [
        {
            "id": "piphi.service.webrtc-sidecar",
            "kind": "platform_service",
            "version_range": ">=0.3.0,<0.4.0",
            "recommended_version": "0.3.0",
            "required": True,
            "shared": True,
            "auto_install": True,
            "reason": "Provides shared camera media sessions and low-latency WebRTC playback.",
        }
    ]


def test_core_allocates_the_runtime_host_port() -> None:
    manifest = _manifest()

    assert manifest["runtime_contract"] == {
        "version": 1,
        "port_binding": "core_allocated",
        "port_env": "PORT",
    }
    assert manifest["runtime"]["linux"]["container"]["ports"] == [
        {"container": 8090}
    ]
