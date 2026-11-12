from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from piphi_webrtc_sidecar.go2rtc import (
    Go2RtcClient,
    Go2RtcError,
    stream_name_for,
    validate_source_url,
)


def test_go2rtc_config_uses_patchable_streams_mapping() -> None:
    config = (Path(__file__).parents[1] / "go2rtc.yaml").read_text(encoding="utf-8")

    assert "streams: {}" not in config
    assert config.endswith("streams:\n")


def test_go2rtc_config_keeps_ffmpeg_relay_private_and_allowlisted() -> None:
    config = (Path(__file__).parents[1] / "go2rtc.yaml").read_text(encoding="utf-8")

    assert 'listen: "127.0.0.1:8554"' in config
    assert 'bin: "/usr/bin/ffmpeg"' in config
    assert '- "/usr/bin/ffmpeg"' in config


def test_source_url_is_limited_to_rtsp_and_stream_names_are_safe() -> None:
    assert validate_source_url("rtsps://user:secret@camera.local/live").startswith("rtsps://")
    assert stream_name_for("Front Door/1") == "piphi_front_door_1"
    with pytest.raises(ValueError, match="rtsp"):
        validate_source_url("http://169.254.169.254/latest/meta-data")


@pytest.mark.anyio
async def test_go2rtc_client_uses_private_api_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/streams":
            return httpx.Response(204)
        if request.url.path == "/api/webrtc":
            return httpx.Response(200, json={"type": "answer", "sdp": "v=0\r\na=answer\r\n"})
        if request.url.path == "/api/frame.jpeg":
            return httpx.Response(200, content=b"jpeg", headers={"content-type": "image/jpeg"})
        return httpx.Response(404)

    client = Go2RtcClient("http://127.0.0.1:1984", httpx.MockTransport(handler))
    await client.upsert_stream("piphi_camera_1", "rtsp://user:secret@camera.local/live")
    answer = await client.exchange_offer("piphi_camera_1", "v=0\r\n")
    content_type, image = await client.snapshot("piphi_camera_1")

    assert answer == "v=0\r\na=answer\r\n"
    assert (content_type, image) == ("image/jpeg", b"jpeg")
    assert requests[0].url.params["name"] == "piphi_camera_1"
    assert requests[0].url.params["src"] == "rtsp://user:secret@camera.local/live"
    assert requests[1].url.params["src"] == "piphi_camera_1"


@pytest.mark.anyio
async def test_go2rtc_client_rejects_malformed_answer() -> None:
    client = Go2RtcClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"not-json"))
    )
    with pytest.raises(Go2RtcError, match="invalid WebRTC answer"):
        await client.exchange_offer("piphi_camera_1", "v=0\r\n")


@pytest.mark.anyio
async def test_go2rtc_client_sanitizes_upstream_signaling_errors() -> None:
    client = Go2RtcClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                500,
                text=(
                    "streams: unsupported codecs from "
                    "rtsps://camera-user:camera-secret@camera.local/live"
                ),
            )
        )
    )

    with pytest.raises(Go2RtcError) as captured:
        await client.exchange_offer("piphi_camera_1", "v=0\r\n")

    message = str(captured.value)
    assert "unsupported codecs" in message
    assert "camera-secret" not in message
    assert "camera.local" not in message
    assert "<camera-source>" in message
