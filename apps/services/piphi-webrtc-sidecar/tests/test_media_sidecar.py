from __future__ import annotations

import asyncio

import httpx
import pytest

from piphi_webrtc_sidecar.go2rtc import Go2RtcClient, Go2RtcError
from piphi_webrtc_sidecar.main import app
from piphi_webrtc_sidecar.media_probe import CameraVideoProbe
from piphi_webrtc_sidecar.media_sessions import CameraMediaSessionBroker
from piphi_webrtc_sidecar.routes.media_sidecar import require_camera_media_authorization


class FakeGo2Rtc:
    def __init__(self) -> None:
        self.sources: dict[str, str] = {}
        self.removed: list[str] = []

    async def upsert_stream(self, name: str, source_url: str) -> None:
        self.sources[name] = source_url

    async def upsert_ffmpeg_stream(
        self, name: str, source_url: str, *, include_audio: bool = False
    ) -> None:
        self.sources[name] = f"ffmpeg:{source_url}:audio={include_audio}"

    async def upsert_browser_compatible_ffmpeg_stream(
        self, name: str, source_url: str, *, include_audio: bool = False
    ) -> None:
        self.sources[name] = f"ffmpeg-h264:{source_url}:audio={include_audio}"

    async def exchange_offer(self, name: str, sdp: str) -> str:
        assert name in self.sources
        assert sdp == "v=0\r\n"
        return "v=0\r\na=answer\r\n"

    async def remove_stream(self, name: str) -> None:
        self.sources.pop(name, None)
        self.removed.append(name)

    async def health(self) -> dict[str, str]:
        return {"version": "1.9.15"}


class RecoveringCleanupGo2Rtc(FakeGo2Rtc):
    def __init__(self, failures: int = 1) -> None:
        super().__init__()
        self.failures_remaining = failures

    async def remove_stream(self, name: str) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise Go2RtcError("go2rtc stream removal failed with status 500")
        await super().remove_stream(name)


async def unknown_probe(*_args, **_kwargs) -> CameraVideoProbe:
    return CameraVideoProbe("mjpeg", "", None, "yuvj420p", 640, 360, 15)


async def unavailable_probe(*_args, **_kwargs) -> None:
    return None


async def browser_safe_probe(*_args, **_kwargs) -> CameraVideoProbe:
    return CameraVideoProbe(
        codec="h264",
        profile="constrained baseline",
        level=41,
        pixel_format="yuv420p",
        width=1920,
        height=1080,
        frames_per_second=30,
    )


class NativeEofGo2Rtc(FakeGo2Rtc):
    def __init__(self) -> None:
        super().__init__()
        self.exchange_attempts = 0
        self.upsert_modes: list[str] = []

    async def upsert_stream(self, name: str, source_url: str) -> None:
        self.upsert_modes.append("native")
        await super().upsert_stream(name, source_url)

    async def upsert_ffmpeg_stream(
        self, name: str, source_url: str, *, include_audio: bool = False
    ) -> None:
        self.upsert_modes.append("ffmpeg")
        await super().upsert_ffmpeg_stream(name, source_url, include_audio=include_audio)

    async def upsert_browser_compatible_ffmpeg_stream(
        self, name: str, source_url: str, *, include_audio: bool = False
    ) -> None:
        self.upsert_modes.append("ffmpeg-h264")
        await super().upsert_browser_compatible_ffmpeg_stream(
            name, source_url, include_audio=include_audio
        )

    async def exchange_offer(self, name: str, sdp: str) -> str:
        self.exchange_attempts += 1
        if self.exchange_attempts == 1:
            raise Go2RtcError(
                "go2rtc WebRTC exchange failed with status 500: EOF",
                operation="webrtc_exchange",
                status_code=500,
                response_detail="EOF",
            )
        return await super().exchange_offer(name, sdp)


class NativeAndCopyEofGo2Rtc(NativeEofGo2Rtc):
    async def exchange_offer(self, name: str, sdp: str) -> str:
        self.exchange_attempts += 1
        if self.exchange_attempts <= 2:
            raise Go2RtcError(
                "go2rtc WebRTC exchange failed with status 500: EOF",
                operation="webrtc_exchange",
                status_code=500,
                response_detail="EOF",
            )
        return await FakeGo2Rtc.exchange_offer(self, name, sdp)


class InvalidOfferGo2Rtc(NativeEofGo2Rtc):
    async def exchange_offer(self, name: str, sdp: str) -> str:
        self.exchange_attempts += 1
        raise Go2RtcError(
            "go2rtc rejected the WebRTC offer",
            operation="webrtc_exchange",
            status_code=400,
            response_detail="invalid SDP",
        )


@pytest.mark.anyio
async def test_sidecar_sessions_are_ephemeral_and_never_return_the_source(monkeypatch) -> None:
    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]
    monkeypatch.setattr("piphi_webrtc_sidecar.routes.media_sidecar.media_session_broker", broker)
    transport = httpx.ASGITransport(app=app)
    request = {
        "contract_version": "camera.media.v1",
        "message_type": "camera.sidecar.session.open",
        "audience": "core-sidecar",
        "source": {
            "contract_version": "camera.media.v1",
            "message_type": "camera.source",
            "audience": "core-sidecar",
            "camera_id": "front-door",
            "source_url": "rtsp://user:top-secret@camera.local/live",
            "source_protocol": "rtsp",
            "preferred_transport": "tcp",
        },
        "offer": {"type": "offer", "sdp": "v=0\r\n", "include_audio": False},
        "idle_timeout_seconds": 60,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        opened = await client.post("/v1/camera-media/sessions", json=request)
        assert opened.status_code == 201
        payload = opened.json()
        assert payload["contract_version"] == "camera.media.v1"
        assert payload["audience"] == "core-sidecar"
        assert "source" not in payload
        assert "camera.local" not in opened.text

        kept_alive = await client.put(
            f"/v1/camera-media/sessions/{payload['session_id']}/keepalive"
        )
        assert kept_alive.status_code == 200
        assert kept_alive.json()["message_type"] == "camera.session.refreshed"

        at_capacity = await client.post("/v1/camera-media/sessions", json=request)
        assert at_capacity.status_code == 429
        assert at_capacity.json()["detail"]["code"] == "CAMERA_CAPACITY_REACHED"

        closed = await client.delete(f"/v1/camera-media/sessions/{payload['session_id']}")
        assert closed.status_code == 204
        status = await client.get("/v1/camera-media/status")

    assert status.json()["active_sessions"] == 0
    assert fake.sources == {}
    assert len(fake.removed) == 1


@pytest.mark.anyio
async def test_sidecar_rejects_browser_audience_and_extra_source_fields() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/camera-media/sessions",
            json={
                "audience": "browser-core",
                "source": {
                    "camera_id": "front-door",
                    "source_url": "rtsp://user:top-secret@camera.local/live",
                    "source_protocol": "rtsp",
                    "password": "must-not-be-accepted",
                },
                "offer": {"type": "offer", "sdp": "v=0"},
            },
        )
    assert response.status_code == 422
    assert "top-secret" not in response.text
    assert "camera.local" not in response.text


@pytest.mark.anyio
async def test_sidecar_requires_constant_time_bearer_auth_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_SIDECAR_TOKEN", "a" * 32)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/v1/camera-media/status")
        wrong = await client.get(
            "/v1/camera-media/status",
            headers={"authorization": f"Bearer {'b' * 32}"},
        )
        accepted = await client.get(
            "/v1/camera-media/status",
            headers={"authorization": f"Bearer {'a' * 32}"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.anyio
async def test_sidecar_fails_closed_without_a_production_token(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    monkeypatch.setenv("PIPHI_ENV", "production")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/camera-media/status")
    assert response.status_code == 503


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/diagnostics", "/contract", "/v1/camera-media/status"])
async def test_all_operational_routes_require_service_identity(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.setenv("PIPHI_SIDECAR_TOKEN", "correct-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get(path)
        wrong = await client.get(path, headers={"Authorization": "Bearer wrong-token"})
    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_sidecar_accepts_runtime_identity_token_in_production(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_SIDECAR_TOKEN", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "r" * 48)
    monkeypatch.setenv("PIPHI_ENV", "production")
    from starlette.requests import Request

    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {'r' * 48}".encode())],
        }
    )
    require_camera_media_authorization(request)


@pytest.mark.anyio
async def test_broker_fails_before_signaling_when_source_probe_fails() -> None:
    from piphi_webrtc_sidecar.media_sessions import CameraSourceUnavailableError

    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, probe=unavailable_probe)  # type: ignore[arg-type]

    with pytest.raises(CameraSourceUnavailableError):
        await broker.open(
            source_url="rtsp://camera.local/live",
            offer_sdp="v=0",
            idle_timeout_seconds=60,
        )

    assert fake.sources == {}


@pytest.mark.anyio
async def test_broker_actively_expires_abandoned_sessions(monkeypatch) -> None:
    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.media_sessions.validate_source_url",
        lambda value: value,
    )
    active, _ = await broker.open(
        source_url="rtsp://camera.local/live",
        offer_sdp="v=0\r\n",
        idle_timeout_seconds=0,
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert broker.active_count == 0
    assert active.stream_name in fake.removed


@pytest.mark.anyio
async def test_close_surfaces_cleanup_failure_and_retries_without_forgetting_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = RecoveringCleanupGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]
    monkeypatch.setattr("piphi_webrtc_sidecar.routes.media_sidecar.media_session_broker", broker)
    active, _ = await broker.open(
        source_url="rtsp://user:top-secret@camera.local/live",
        offer_sdp="v=0",
        idle_timeout_seconds=60,
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        failed = await client.delete(f"/v1/camera-media/sessions/{active.session_id}")
        status = await client.get("/v1/camera-media/status")

    assert failed.status_code == 502
    assert failed.json()["detail"]["code"] == "CAMERA_SESSION_CLEANUP_FAILED"
    assert "top-secret" not in failed.text
    assert broker.active_count == 1
    assert broker.cleanup_pending_count == 1
    assert active.stream_name in fake.sources
    assert status.json()["ready"] is False
    assert status.json()["degraded_reason"] == "session_cleanup_failed"
    assert status.json()["cleanup_pending_sessions"] == 1

    await asyncio.sleep(1.1)

    assert broker.active_count == 0
    assert broker.cleanup_pending_count == 0
    assert fake.sources == {}


@pytest.mark.anyio
async def test_expiry_retains_and_retries_failed_cleanup(monkeypatch) -> None:
    fake = RecoveringCleanupGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.media_sessions.validate_source_url", lambda value: value
    )
    active, _ = await broker.open(
        source_url="rtsp://camera.local/live",
        offer_sdp="v=0",
        idle_timeout_seconds=0,
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert broker.active_count == 1
    assert broker.cleanup_pending_count == 1
    assert active.stream_name in fake.sources

    await asyncio.sleep(1.1)

    assert broker.active_count == 0
    assert broker.cleanup_pending_count == 0
    assert fake.sources == {}


@pytest.mark.anyio
async def test_broker_restores_terminal_sdp_line_ending() -> None:
    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]

    active, answer = await broker.open(
        source_url="rtsp://camera.local/live",
        offer_sdp="v=0",
        idle_timeout_seconds=60,
    )

    assert answer == "v=0\r\na=answer\r\n"
    await broker.close(active.session_id)


@pytest.mark.anyio
async def test_broker_retries_browser_normalization_eof_through_ffmpeg_copy_relay() -> None:
    fake = NativeEofGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]

    active, answer = await broker.open(
        source_url="rtsp://user:top-secret@camera.local/stream0",
        offer_sdp="v=0\r\n",
        idle_timeout_seconds=60,
    )

    assert answer == "v=0\r\na=answer\r\n"
    assert fake.upsert_modes == ["ffmpeg-h264", "ffmpeg"]
    assert fake.exchange_attempts == 2
    assert fake.sources[active.stream_name].startswith("ffmpeg:rtsp://")
    assert fake.removed == [active.stream_name]
    await broker.close(active.session_id)


@pytest.mark.anyio
async def test_broker_falls_back_to_native_when_ffmpeg_sources_cannot_match_offer() -> None:
    fake = NativeAndCopyEofGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]

    active, answer = await broker.open(
        source_url="rtsp://user:top-secret@camera.local/stream0",
        offer_sdp="v=0\r\n",
        idle_timeout_seconds=60,
    )

    assert answer == "v=0\r\na=answer\r\n"
    assert fake.upsert_modes == ["ffmpeg-h264", "ffmpeg", "native"]
    assert fake.exchange_attempts == 3
    assert fake.sources[active.stream_name].startswith("rtsp://")
    assert fake.removed == [active.stream_name, active.stream_name]
    await broker.close(active.session_id)


@pytest.mark.anyio
async def test_broker_does_not_retry_offer_validation_failures() -> None:
    fake = InvalidOfferGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]

    with pytest.raises(Go2RtcError, match="rejected the WebRTC offer"):
        await broker.open(
            source_url="rtsp://camera.local/stream0",
            offer_sdp="v=0\r\n",
            idle_timeout_seconds=60,
        )

    assert fake.upsert_modes == ["ffmpeg-h264"]
    assert fake.exchange_attempts == 1
    assert fake.sources == {}


@pytest.mark.anyio
async def test_broker_copies_conservatively_verified_browser_safe_h264() -> None:
    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=browser_safe_probe)  # type: ignore[arg-type]

    active, answer = await broker.open(
        source_url="rtsp://camera.local/stream0",
        offer_sdp="v=0\r\n",
        idle_timeout_seconds=60,
    )

    assert answer == "v=0\r\na=answer\r\n"
    assert active.strategy == "ffmpeg-copy"
    assert fake.sources[active.stream_name].startswith("ffmpeg:rtsp://")
    await broker.close(active.session_id)


@pytest.mark.anyio
async def test_ffmpeg_copy_relay_keeps_credentials_inside_go2rtc_request() -> None:
    captured_source = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_source
        captured_source = request.url.params["src"]
        return httpx.Response(200)

    client = Go2RtcClient(transport=httpx.MockTransport(handler))
    source = "rtsp://user:top-secret@camera.local/stream0"

    await client.upsert_ffmpeg_stream("camera", source, include_audio=False)

    assert captured_source == f"ffmpeg:{source}#video=copy#audio=0"


@pytest.mark.anyio
async def test_ffmpeg_browser_relay_transcodes_video_and_normalizes_requested_audio() -> None:
    captured_source = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_source
        captured_source = request.url.params["src"]
        return httpx.Response(200)

    client = Go2RtcClient(transport=httpx.MockTransport(handler))
    source = "rtsp://user:top-secret@camera.local/stream0"

    await client.upsert_browser_compatible_ffmpeg_stream("camera", source, include_audio=True)

    assert captured_source == f"ffmpeg:{source}#video=h264#audio=opus"


@pytest.mark.anyio
async def test_keepalive_renews_activity_based_expiry() -> None:
    fake = FakeGo2Rtc()
    broker = CameraMediaSessionBroker(fake, capacity=1, probe=unknown_probe)  # type: ignore[arg-type]
    active, _ = await broker.open(
        source_url="rtsp://camera.local/live",
        offer_sdp="v=0",
        idle_timeout_seconds=60,
    )

    refreshed = await broker.touch(active.session_id)

    assert refreshed is not None
    assert refreshed.expires_at >= active.expires_at
    assert broker.active_count == 1
    await broker.close(active.session_id)
