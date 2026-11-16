from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from piphi_webrtc_sidecar import go2rtc as go2rtc_module


@pytest.mark.anyio
async def test_managed_process_waits_for_real_control_plane(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    binary = tmp_path / "go2rtc"
    binary.write_bytes(b"binary")
    monkeypatch.setenv("GO2RTC_BINARY", str(binary))
    monkeypatch.setenv("GO2RTC_CONFIG", "/tmp/go2rtc.yaml")
    process = Mock(returncode=None)
    process.wait = AsyncMock(return_value=0)
    create_process = AsyncMock(return_value=process)
    monkeypatch.setattr(go2rtc_module.asyncio, "create_subprocess_exec", create_process)
    health = AsyncMock(return_value={"version": "1.9.15"})
    monkeypatch.setattr(
        go2rtc_module,
        "Go2RtcClient",
        Mock(return_value=Mock(health=health)),
    )
    managed = go2rtc_module.Go2RtcProcess()

    await managed.start()

    create_process.assert_awaited_once_with(
        str(binary),
        "-config",
        "/tmp/go2rtc.yaml",
        stdout=go2rtc_module.asyncio.subprocess.DEVNULL,
        stderr=go2rtc_module.asyncio.subprocess.STDOUT,
    )
    health.assert_awaited_once()
    await managed.stop()
    process.terminate.assert_called_once()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", 5.0), ("20", 20.0), ("90", 30.0), ("invalid", 15.0)],
)
def test_startup_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: float,
) -> None:
    monkeypatch.setenv("GO2RTC_STARTUP_TIMEOUT_SECONDS", value)

    assert go2rtc_module._startup_timeout_seconds() == expected
