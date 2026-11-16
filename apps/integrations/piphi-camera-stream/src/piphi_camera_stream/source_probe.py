from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

ProbeReason = Literal["available", "probe_unavailable", "timeout", "source_unreachable"]
MAX_SNAPSHOT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class SourceProbeResult:
    available: bool
    reason: ProbeReason


async def probe_camera_source(
    source_url: str,
    *,
    preferred_transport: str = "auto",
    timeout_seconds: int = 10,
) -> SourceProbeResult:
    """Verify that ffprobe can authenticate and inspect one camera video stream."""
    command = ["ffprobe", "-v", "error"]
    if preferred_transport in {"tcp", "udp"}:
        command.extend(["-rtsp_transport", preferred_transport])
    command.extend(
        [
            "-rw_timeout",
            str(timeout_seconds * 1_000_000),
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=index",
            "-of",
            "csv=p=0",
            source_url,
        ]
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return SourceProbeResult(available=False, reason="probe_unavailable")

    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds + 2,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return SourceProbeResult(available=False, reason="timeout")

    if process.returncode != 0 or not stdout.strip() or len(stdout) > 4096:
        return SourceProbeResult(available=False, reason="source_unreachable")
    return SourceProbeResult(available=True, reason="available")


async def capture_camera_snapshot(
    source_url: str,
    *,
    preferred_transport: str = "auto",
    timeout_seconds: int = 10,
) -> bytes | None:
    """Capture one bounded JPEG frame without logging or returning the source URL."""
    command = ["ffmpeg", "-v", "error"]
    if preferred_transport in {"tcp", "udp"}:
        command.extend(["-rtsp_transport", preferred_transport])
    command.extend(
        [
            "-rw_timeout",
            str(timeout_seconds * 1_000_000),
            "-i",
            source_url,
            "-frames:v",
            "1",
            "-vf",
            "scale=min(1920\\,iw):-2",
            "-q:v",
            "3",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None

    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds + 2,
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    if (
        process.returncode != 0
        or not stdout.startswith(b"\xff\xd8")
        or not stdout.endswith(b"\xff\xd9")
        or len(stdout) > MAX_SNAPSHOT_BYTES
    ):
        return None
    return stdout
