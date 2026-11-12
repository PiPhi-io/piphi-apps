from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal

from .go2rtc import validate_source_url

PreferredTransport = Literal["tcp", "udp", "auto"]


@dataclass(frozen=True)
class CameraVideoProbe:
    codec: str
    profile: str
    level: int | None
    pixel_format: str
    width: int | None
    height: int | None
    frames_per_second: float | None

    @property
    def browser_safe_h264(self) -> bool:
        """Return true only for the conservative Chromium/WebRTC passthrough set."""
        return (
            self.codec == "h264"
            and self.profile in {"baseline", "constrained baseline"}
            and (self.level is None or self.level <= 42)
            and self.pixel_format in {"yuv420p", "yuvj420p"}
            and (self.width is None or self.width <= 3840)
            and (self.height is None or self.height <= 2160)
            and (self.frames_per_second is None or self.frames_per_second <= 60)
        )


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _frame_rate(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    numerator, separator, denominator = text.partition("/")
    try:
        parsed = float(numerator) / float(denominator) if separator else float(text)
    except (ValueError, ZeroDivisionError):
        return None
    return parsed if parsed > 0 else None


def parse_ffprobe_video(payload: object) -> CameraVideoProbe | None:
    if not isinstance(payload, dict):
        return None
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams or not isinstance(streams[0], dict):
        return None
    stream = streams[0]
    codec = str(stream.get("codec_name") or "").strip().lower()
    if not codec:
        return None
    return CameraVideoProbe(
        codec=codec,
        profile=str(stream.get("profile") or "").strip().lower(),
        level=_positive_int(stream.get("level")),
        pixel_format=str(stream.get("pix_fmt") or "").strip().lower(),
        width=_positive_int(stream.get("width")),
        height=_positive_int(stream.get("height")),
        frames_per_second=_frame_rate(stream.get("avg_frame_rate")),
    )


async def probe_camera_video(
    source_url: str,
    *,
    preferred_transport: PreferredTransport = "auto",
    connect_timeout_seconds: int = 10,
) -> CameraVideoProbe | None:
    """Inspect one video stream without retaining or logging camera credentials."""
    source = validate_source_url(source_url)
    command = ["ffprobe", "-v", "error"]
    if preferred_transport in {"tcp", "udp"}:
        command.extend(["-rtsp_transport", preferred_transport])
    command.extend(
        [
            "-rw_timeout",
            str(connect_timeout_seconds * 1_000_000),
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,profile,level,pix_fmt,width,height,avg_frame_rate",
            "-of",
            "json",
            source,
        ]
    )
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=connect_timeout_seconds + 2
        )
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    if process.returncode != 0 or len(stdout) > 64 * 1024:
        return None
    try:
        return parse_ffprobe_video(json.loads(stdout))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
