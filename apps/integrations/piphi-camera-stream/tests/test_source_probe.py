from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from piphi_camera_stream.source_probe import (
    capture_camera_snapshot,
    probe_camera_source,
)


@pytest.mark.anyio
async def test_probe_requires_a_real_video_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"0\n", b""))
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", create_process)

    result = await probe_camera_source(
        "rtsp://user:secret@camera.local/live",
        preferred_transport="tcp",
    )

    assert result.available is True
    assert result.reason == "available"
    command = create_process.await_args.args
    assert command[:5] == ("ffprobe", "-v", "error", "-rtsp_transport", "tcp")


@pytest.mark.anyio
async def test_probe_reports_failed_authentication_or_transport_as_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.returncode = 1
    process.communicate = AsyncMock(return_value=(b"", b"authentication failed"))
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )

    result = await probe_camera_source("rtsp://camera.local/live")

    assert result.available is False
    assert result.reason == "source_unreachable"


@pytest.mark.anyio
async def test_probe_fails_safely_when_ffprobe_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("ffprobe")),
    )

    result = await probe_camera_source("rtsp://camera.local/live")

    assert result.available is False
    assert result.reason == "probe_unavailable"


@pytest.mark.anyio
async def test_snapshot_accepts_only_a_bounded_jpeg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"\xff\xd8frame\xff\xd9", b""))
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )

    image = await capture_camera_snapshot("rtsp://camera.local/live")

    assert image == b"\xff\xd8frame\xff\xd9"


@pytest.mark.anyio
async def test_snapshot_rejects_non_jpeg_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = Mock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(b"not-an-image", b""))
    monkeypatch.setattr(
        "asyncio.create_subprocess_exec", AsyncMock(return_value=process)
    )

    assert await capture_camera_snapshot("rtsp://camera.local/live") is None
