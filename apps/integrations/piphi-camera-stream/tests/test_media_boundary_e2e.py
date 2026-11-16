from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

SERVICES = Path(__file__).resolve().parents[3] / "services"
WEBRTC_SOURCE = SERVICES / "piphi-webrtc-sidecar" / "src"
if not WEBRTC_SOURCE.is_dir():  # pragma: no cover - standalone source distribution
    pytest.skip("WebRTC service source is not available", allow_module_level=True)
sys.path.insert(0, str(WEBRTC_SOURCE))

from piphi_webrtc_sidecar.main import app as media_app
from piphi_webrtc_sidecar.media_sessions import CameraMediaSessionBroker

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

    async def remove_stream(self, name: str) -> None:
        self.sources.pop(name, None)


async def no_probe(*_args, **_kwargs) -> None:
    return None


@pytest.mark.anyio
async def test_core_identity_to_media_session_keeps_source_secret_inside_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    camera_transport = httpx.ASGITransport(app=camera_app)
    async with httpx.AsyncClient(
        transport=camera_transport, base_url="http://camera"
    ) as client:
        source = await client.get(
            "/v1/cameras/front-door/source",
            headers={
                "X-PiPhi-Integration-Token": "runtime-token",
                "X-Container-Id": "camera-container",
            },
        )
    assert source.status_code == 200

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
                "source": source.json(),
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
