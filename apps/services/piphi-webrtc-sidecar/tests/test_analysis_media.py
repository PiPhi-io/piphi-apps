from __future__ import annotations

import asyncio

import httpx
import pytest

from piphi_webrtc_sidecar.analysis_media import (
    MAX_ANALYSIS_MEDIA_BYTES,
    AnalysisMediaBroker,
    AnalysisMediaCapacityError,
    AnalysisMediaSizeError,
    AnalysisMediaTypeError,
)
from piphi_webrtc_sidecar.go2rtc import Go2RtcError
from piphi_webrtc_sidecar.main import app

JPEG = b"\xff\xd8\xff\xe0synthetic-image"


class SnapshotGo2Rtc:
    def __init__(self, content_type: str = "image/jpeg", content: bytes = JPEG) -> None:
        self.content_type = content_type
        self.content = content
        self.sources: dict[str, str] = {}
        self.removed: list[str] = []

    async def upsert_stream(self, name: str, source_url: str) -> None:
        self.sources[name] = source_url

    async def snapshot(self, name: str) -> tuple[str, bytes]:
        assert name in self.sources
        return self.content_type, self.content

    async def remove_stream(self, name: str) -> None:
        self.sources.pop(name, None)
        self.removed.append(name)


class CleanupFailureGo2Rtc(SnapshotGo2Rtc):
    def __init__(self) -> None:
        super().__init__()
        self.failures_remaining = 1

    async def remove_stream(self, name: str) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise Go2RtcError(
                "cleanup exposed rtsp://raw-user:raw-password@private-camera.local/live"
            )
        await super().remove_stream(name)


class UnavailableSnapshotGo2Rtc(SnapshotGo2Rtc):
    async def snapshot(self, name: str) -> tuple[str, bytes]:
        raise Go2RtcError(
            "snapshot exposed rtsp://raw-user:raw-password@private-camera.local/live"
        )


def issue_request(source_url: str = "rtsp://user:secret@camera.local/live") -> dict[str, object]:
    return {
        "contract_version": "camera.analysis-media.v1",
        "message_type": "camera.analysis-media.issue",
        "audience": "core-sidecar",
        "source": {
            "contract_version": "camera.media.v1",
            "message_type": "camera.source",
            "audience": "core-sidecar",
            "camera_id": "front-door",
            "source_url": source_url,
            "source_protocol": "rtsp",
            "preferred_transport": "tcp",
        },
        "ttl_seconds": 30,
    }


@pytest.mark.anyio
async def test_issued_image_is_opaque_one_time_and_non_cacheable(monkeypatch) -> None:
    fake = SnapshotGo2Rtc()
    broker = AnalysisMediaBroker(fake, capacity=2)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.routes.analysis_media.analysis_media_broker", broker
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        issued = await client.post("/v1/analysis-media", json=issue_request())
        assert issued.status_code == 201
        media_ref = issued.json()["media_ref"]
        assert "camera.local" not in issued.text
        assert "secret" not in issued.text
        assert issued.headers["cache-control"] == "no-store"

        image = await client.get(f"/v1/analysis-media/{media_ref}")
        replay = await client.get(f"/v1/analysis-media/{media_ref}")

    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"
    assert image.headers["cache-control"] == "no-store"
    assert image.content == JPEG
    assert replay.status_code == 404
    assert broker.active_count == 0
    assert broker.stored_bytes == 0
    assert fake.sources == {}
    assert len(fake.removed) == 1


@pytest.mark.anyio
async def test_concurrent_retrieval_consumes_reference_atomically() -> None:
    broker = AnalysisMediaBroker(SnapshotGo2Rtc())  # type: ignore[arg-type]
    issued = await broker.issue(source_url="rtsp://camera.local/live", ttl_seconds=30)

    first, second = await asyncio.gather(
        broker.consume(issued.media_ref), broker.consume(issued.media_ref)
    )

    assert sum(item is not None for item in (first, second)) == 1
    assert broker.stored_bytes == 0


@pytest.mark.anyio
async def test_reference_actively_expires_and_rejects_replay() -> None:
    broker = AnalysisMediaBroker(SnapshotGo2Rtc())  # type: ignore[arg-type]
    issued = await broker.issue(source_url="rtsp://camera.local/live", ttl_seconds=0)

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert await broker.consume(issued.media_ref) is None
    assert broker.active_count == 0
    assert broker.stored_bytes == 0


@pytest.mark.anyio
async def test_item_and_byte_capacity_are_bounded() -> None:
    item_broker = AnalysisMediaBroker(SnapshotGo2Rtc(), capacity=1)  # type: ignore[arg-type]
    await item_broker.issue(source_url="rtsp://camera.local/one", ttl_seconds=30)
    with pytest.raises(AnalysisMediaCapacityError):
        await item_broker.issue(source_url="rtsp://camera.local/two", ttl_seconds=30)
    await item_broker.close_all()

    large_jpeg = b"\xff\xd8\xff" + b"x" * (6 * 1024 * 1024)
    byte_broker = AnalysisMediaBroker(
        SnapshotGo2Rtc(content=large_jpeg), capacity=2, byte_capacity=MAX_ANALYSIS_MEDIA_BYTES
    )  # type: ignore[arg-type]
    await byte_broker.issue(source_url="rtsp://camera.local/one", ttl_seconds=30)
    with pytest.raises(AnalysisMediaCapacityError):
        await byte_broker.issue(source_url="rtsp://camera.local/two", ttl_seconds=30)
    await byte_broker.close_all()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content_type", "content", "error"),
    [
        ("text/plain", JPEG, AnalysisMediaTypeError),
        ("image/png", JPEG, AnalysisMediaTypeError),
        ("image/jpeg", b"", AnalysisMediaSizeError),
        (
            "image/jpeg",
            b"\xff\xd8\xff" + b"x" * MAX_ANALYSIS_MEDIA_BYTES,
            AnalysisMediaSizeError,
        ),
    ],
)
async def test_invalid_media_is_rejected_after_stream_cleanup(
    content_type: str, content: bytes, error: type[RuntimeError]
) -> None:
    fake = SnapshotGo2Rtc(content_type, content)
    broker = AnalysisMediaBroker(fake)  # type: ignore[arg-type]

    with pytest.raises(error):
        await broker.issue(source_url="rtsp://camera.local/live", ttl_seconds=30)

    assert fake.sources == {}
    assert len(fake.removed) == 1
    assert broker.active_count == 0


@pytest.mark.anyio
async def test_cleanup_failure_publishes_no_reference_and_redacts_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = CleanupFailureGo2Rtc()
    broker = AnalysisMediaBroker(fake, capacity=1)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.routes.analysis_media.analysis_media_broker", broker
    )
    caplog.set_level("WARNING")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/analysis-media",
            json=issue_request("rtsp://raw-user:raw-password@private-camera.local/live"),
        )
        while_cleanup_pending = await client.post(
            "/v1/analysis-media", json=issue_request()
        )

    evidence = response.text + caplog.text
    assert response.status_code == 502
    assert while_cleanup_pending.status_code == 429
    assert broker.active_count == 0
    assert "raw-user" not in evidence
    assert "raw-password" not in evidence
    assert "private-camera.local" not in evidence

    await asyncio.sleep(1.1)
    assert fake.sources == {}
    assert broker._cleanup_tasks == {}


@pytest.mark.anyio
async def test_unavailable_camera_failure_is_sanitized_and_stream_is_removed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = UnavailableSnapshotGo2Rtc()
    broker = AnalysisMediaBroker(fake)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "piphi_webrtc_sidecar.routes.analysis_media.analysis_media_broker", broker
    )
    caplog.set_level("WARNING")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/analysis-media",
            json=issue_request("rtsp://raw-user:raw-password@private-camera.local/live"),
        )

    evidence = response.text + caplog.text
    assert response.status_code == 502
    assert fake.sources == {}
    assert len(fake.removed) == 1
    assert "raw-user" not in evidence
    assert "raw-password" not in evidence
    assert "private-camera.local" not in evidence


@pytest.mark.anyio
async def test_revoke_removes_reference() -> None:
    broker = AnalysisMediaBroker(SnapshotGo2Rtc())  # type: ignore[arg-type]
    issued = await broker.issue(source_url="rtsp://camera.local/live", ttl_seconds=30)

    assert await broker.revoke(issued.media_ref) is True
    assert await broker.consume(issued.media_ref) is None
    assert await broker.revoke(issued.media_ref) is False


@pytest.mark.anyio
async def test_analysis_media_routes_require_service_identity(monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.setenv("PIPHI_SIDECAR_TOKEN", "correct-token")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        issue = await client.post("/v1/analysis-media", json=issue_request())
        retrieve = await client.get("/v1/analysis-media/not-issued")
        revoke = await client.delete("/v1/analysis-media/not-issued")

    assert issue.status_code == 401
    assert retrieve.status_code == 401
    assert revoke.status_code == 401
    for response in (issue, retrieve, revoke):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
