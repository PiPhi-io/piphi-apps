from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

SERVICES = Path(__file__).resolve().parents[3] / "services"
WEBRTC_SOURCE = SERVICES / "piphi-webrtc-sidecar" / "src"
WYZE_SOURCE = SERVICES / "piphi-wyze-camera-service" / "src"
if not WEBRTC_SOURCE.is_dir():  # pragma: no cover - standalone source distribution
    pytest.skip("WebRTC service source is not available", allow_module_level=True)
sys.path.insert(0, str(WEBRTC_SOURCE))
sys.path.insert(0, str(WYZE_SOURCE))

from piphi_webrtc_sidecar.analysis_media import AnalysisMediaBroker
from piphi_webrtc_sidecar.main import app as media_app
from piphi_webrtc_sidecar.media_sessions import CameraMediaSessionBroker
from piphi_wyze_camera_service.bridge import BridgeRuntimeConfig, WyzeBridgeSupervisor

from piphi_camera_stream.main import app as camera_app
from piphi_camera_stream.schemas import DeviceConfig
from piphi_camera_stream.source_probe import SourceProbeResult
from piphi_camera_stream.state import apply_config, registry


class FakeGo2Rtc:
    def __init__(self) -> None:
        self.sources: dict[str, str] = {}

    async def upsert_stream(self, name: str, source_url: str) -> None:
        self.sources[name] = source_url

    async def upsert_ffmpeg_stream(
        self,
        name: str,
        source_url: str,
        *,
        include_audio: bool = False,
    ) -> None:
        self.sources[name] = source_url

    async def upsert_browser_compatible_ffmpeg_stream(
        self,
        name: str,
        source_url: str,
        *,
        include_audio: bool = False,
    ) -> None:
        self.sources[name] = source_url

    async def exchange_offer(self, name: str, sdp: str) -> str:
        assert name in self.sources
        return "v=0\r\na=answer\r\n"

    async def snapshot(self, name: str) -> tuple[str, bytes]:
        assert name in self.sources
        return "image/jpeg", b"\xff\xd8\xff\xe0synthetic-camera-image"

    async def remove_stream(self, name: str) -> None:
        self.sources.pop(name, None)


async def no_probe(*_args, **_kwargs):
    from piphi_webrtc_sidecar.media_probe import CameraVideoProbe

    return CameraVideoProbe("mjpeg", "", None, "yuvj420p", 640, 360, 15)


async def configured_camera_source(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-token")
    monkeypatch.setenv("PIPHI_CONTAINER_ID", "camera-container")
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(True, "available")),
    )
    registry.entries.clear()
    registry.state_snapshots.clear()
    await apply_config(
        DeviceConfig(
            id="front-door",
            source_url="rtsp://user:top-secret@camera.local/live",
        )
    )
    transport = httpx.ASGITransport(app=camera_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://camera") as client:
        response = await client.get(
            "/v1/cameras/front-door/source",
            headers={
                "X-PiPhi-Integration-Token": "runtime-token",
                "X-Container-Id": "camera-container",
            },
        )
    assert response.status_code == 200
    return response.json()


@pytest.mark.anyio
async def test_core_identity_to_media_session_keeps_source_secret_inside_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await configured_camera_source(monkeypatch)

    fake_go2rtc = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake_go2rtc, probe=no_probe)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.routes.media_sidecar.media_session_broker", broker
    )
    media_transport = httpx.ASGITransport(app=media_app)
    async with httpx.AsyncClient(
        transport=media_transport, base_url="http://media"
    ) as client:
        opened = await client.post(
            "/v1/camera-media/sessions",
            headers={"Authorization": "Bearer runtime-token"},
            json={
                "contract_version": "camera.media.v1",
                "message_type": "camera.sidecar.session.open",
                "audience": "core-sidecar",
                "source": source,
                "offer": {"type": "offer", "sdp": "v=0", "include_audio": False},
                "idle_timeout_seconds": 60,
            },
        )
        assert opened.status_code == 201
        assert "top-secret" not in opened.text
        assert "camera.local" not in opened.text
        session_id = opened.json()["session_id"]
        closed = await client.delete(
            f"/v1/camera-media/sessions/{session_id}",
            headers={"Authorization": "Bearer runtime-token"},
        )

    assert closed.status_code == 204
    assert broker.active_count == 0
    assert fake_go2rtc.sources == {}


@pytest.mark.anyio
async def test_camera_source_issues_one_time_analysis_media_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = await configured_camera_source(monkeypatch)

    fake_go2rtc = FakeGo2Rtc()
    broker = AnalysisMediaBroker(fake_go2rtc)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.routes.analysis_media.analysis_media_broker", broker
    )
    media_transport = httpx.ASGITransport(app=media_app)
    headers = {"Authorization": "Bearer runtime-token"}
    async with httpx.AsyncClient(
        transport=media_transport, base_url="http://media"
    ) as client:
        issued = await client.post(
            "/v1/analysis-media",
            headers=headers,
            json={"source": source, "ttl_seconds": 30},
        )
        assert issued.status_code == 201
        assert "top-secret" not in issued.text
        assert "camera.local" not in issued.text
        media_ref = issued.json()["media_ref"]

        image = await client.get(f"/v1/analysis-media/{media_ref}", headers=headers)
        replay = await client.get(f"/v1/analysis-media/{media_ref}", headers=headers)

    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.content == b"\xff\xd8\xff\xe0synthetic-camera-image"
    assert replay.status_code == 404
    assert broker.active_count == 0
    assert fake_go2rtc.sources == {}


@pytest.mark.anyio
async def test_wyze_descriptor_is_accepted_without_broadening_camera_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_config = BridgeRuntimeConfig(
        advertised_host="wyze-bridge",
        enabled_camera_names=("Doggy Cam",),
        stream_password="ephemeral-stream-secret",
        web_username="piphi",
        web_password="private-control-secret",
    )
    cameras = WyzeBridgeSupervisor._normalize_cameras(
        {
            "doggy-cam": {
                "nickname": "Doggy Cam",
                "product_model": "fixture-model",
                "status": "connected",
            }
        }
    )
    descriptor = WyzeBridgeSupervisor._with_source_url(cameras[0], runtime_config)
    monkeypatch.setattr(
        "piphi_camera_stream.state.probe_camera_source",
        AsyncMock(return_value=SourceProbeResult(True, "available")),
    )
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-token")
    registry.entries.clear()
    registry.state_snapshots.clear()

    await apply_config(
        DeviceConfig(
            id="doggy-cam",
            source_url=descriptor["source_url"],
            alias=descriptor["name"],
        )
    )
    transport = httpx.ASGITransport(app=camera_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://camera"
    ) as client:
        source = await client.get(
            "/v1/cameras/doggy-cam/source",
            headers={"X-PiPhi-Integration-Token": "runtime-token"},
        )

    assert source.status_code == 200
    assert source.json()["source_url"] == descriptor["source_url"]
    assert source.headers["cache-control"] == "no-store"
