from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal
from uuid import uuid4

from .go2rtc import Go2RtcClient, Go2RtcError, go2rtc, validate_source_url
from .media_probe import CameraVideoProbe, PreferredTransport, probe_camera_video

MediaStrategy = Literal["ffmpeg-copy", "ffmpeg-h264", "native"]
ProbeFunction = Callable[..., Awaitable[CameraVideoProbe | None]]


@dataclass(frozen=True)
class ActiveMediaSession:
    session_id: str
    stream_name: str
    expires_at: datetime
    strategy: MediaStrategy
    idle_timeout_seconds: int


class CameraMediaSessionBroker:
    """Owns only short-lived transport sessions; camera configuration stays elsewhere."""

    def __init__(
        self,
        client: Go2RtcClient | None = None,
        *,
        capacity: int | None = None,
        probe: ProbeFunction = probe_camera_video,
        probe_ttl_seconds: int = 300,
    ) -> None:
        self.client = client or go2rtc
        self.capacity = capacity or max(1, int(os.getenv("PIPHI_CAMERA_SESSION_CAPACITY", "16")))
        self.probe = probe
        self.probe_ttl_seconds = max(0, probe_ttl_seconds)
        self._sessions: dict[str, ActiveMediaSession] = {}
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self._cleanup_failures: dict[str, int] = {}
        self._probe_cache: dict[bytes, tuple[float, CameraVideoProbe | None]] = {}
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._sessions)

    @property
    def cleanup_pending_count(self) -> int:
        return len(self._cleanup_failures)

    @property
    def degraded_reason(self) -> str | None:
        return "session_cleanup_failed" if self._cleanup_failures else None

    async def open(
        self,
        *,
        source_url: str,
        offer_sdp: str,
        idle_timeout_seconds: int,
        preferred_transport: PreferredTransport = "auto",
        connect_timeout_seconds: int = 10,
        include_audio: bool = False,
    ) -> tuple[ActiveMediaSession, str]:
        source = validate_source_url(source_url)
        normalized_offer = offer_sdp if offer_sdp.endswith("\n") else f"{offer_sdp}\r\n"
        async with self._lock:
            await self._expire_locked()
            if len(self._sessions) >= self.capacity:
                raise CameraMediaCapacityError("camera media service is at session capacity")
            session_id = uuid4().hex
            stream_name = f"piphi_session_{session_id}"
            probe = await self._probe_source(
                source,
                preferred_transport=preferred_transport,
                connect_timeout_seconds=connect_timeout_seconds,
            )
            if probe is None:
                raise CameraSourceUnavailableError(
                    "camera source did not provide a probeable video stream"
                )
            strategies: tuple[MediaStrategy, ...] = (
                ("ffmpeg-copy", "ffmpeg-h264", "native")
                if probe is not None and probe.browser_safe_h264
                else ("ffmpeg-h264", "ffmpeg-copy", "native")
            )
            answer_sdp, selected_strategy = await self._exchange_with_fallbacks(
                stream_name=stream_name,
                source=source,
                offer_sdp=normalized_offer,
                strategies=strategies,
                include_audio=include_audio,
            )
            active = ActiveMediaSession(
                session_id=session_id,
                stream_name=stream_name,
                expires_at=datetime.now(UTC) + timedelta(seconds=idle_timeout_seconds),
                strategy=selected_strategy,
                idle_timeout_seconds=idle_timeout_seconds,
            )
            self._sessions[session_id] = active
            self._expiry_tasks[session_id] = asyncio.create_task(
                self._expire_after(session_id, idle_timeout_seconds),
                name=f"camera-media-expiry:{session_id}",
            )
            return active, answer_sdp

    async def _probe_source(
        self,
        source: str,
        *,
        preferred_transport: PreferredTransport,
        connect_timeout_seconds: int,
    ) -> CameraVideoProbe | None:
        cache_key = hashlib.sha256(source.encode("utf-8")).digest()
        cached = self._probe_cache.get(cache_key)
        now = monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            result = await self.probe(
                source,
                preferred_transport=preferred_transport,
                connect_timeout_seconds=connect_timeout_seconds,
            )
        except (OSError, ValueError):
            result = None
        self._probe_cache[cache_key] = (now + self.probe_ttl_seconds, result)
        if len(self._probe_cache) > 256:
            expired = [key for key, (deadline, _) in self._probe_cache.items() if deadline <= now]
            for key in expired:
                self._probe_cache.pop(key, None)
            while len(self._probe_cache) > 256:
                self._probe_cache.pop(next(iter(self._probe_cache)))
        return result

    async def _exchange_with_fallbacks(
        self,
        *,
        stream_name: str,
        source: str,
        offer_sdp: str,
        strategies: tuple[MediaStrategy, ...],
        include_audio: bool,
    ) -> tuple[str, MediaStrategy]:
        for index, strategy in enumerate(strategies):
            await self._configure_stream(
                stream_name,
                source,
                strategy,
                include_audio=include_audio,
            )
            try:
                return await self.client.exchange_offer(stream_name, offer_sdp), strategy
            except Go2RtcError as exc:
                await self._remove_stream(stream_name)
                if not exc.is_native_source_eof or index == len(strategies) - 1:
                    raise
            except Exception:
                await self._remove_stream(stream_name)
                raise
        raise RuntimeError("camera media strategy selection failed")

    async def _configure_stream(
        self,
        stream_name: str,
        source: str,
        strategy: MediaStrategy,
        *,
        include_audio: bool,
    ) -> None:
        if strategy == "ffmpeg-copy":
            await self.client.upsert_ffmpeg_stream(
                stream_name,
                source,
                include_audio=include_audio,
            )
        elif strategy == "ffmpeg-h264":
            await self.client.upsert_browser_compatible_ffmpeg_stream(
                stream_name,
                source,
                include_audio=include_audio,
            )
        else:
            await self.client.upsert_stream(stream_name, source)

    async def touch(self, session_id: str) -> ActiveMediaSession | None:
        async with self._lock:
            active = self._sessions.get(session_id)
            if active is None or session_id in self._cleanup_failures:
                return None
            refreshed = replace(
                active,
                expires_at=datetime.now(UTC) + timedelta(seconds=active.idle_timeout_seconds),
            )
            self._sessions[session_id] = refreshed
            expiry_task = self._expiry_tasks.pop(session_id, None)
            if expiry_task is not None and expiry_task is not asyncio.current_task():
                expiry_task.cancel()
            self._expiry_tasks[session_id] = asyncio.create_task(
                self._expire_after(session_id, active.idle_timeout_seconds),
                name=f"camera-media-expiry:{session_id}",
            )
            return refreshed

    async def close(self, session_id: str) -> bool:
        async with self._lock:
            active = self._sessions.get(session_id)
            if active is None:
                return False
            try:
                await self._remove_stream(active.stream_name)
            except CameraMediaCleanupError:
                failures = self._cleanup_failures.get(session_id, 0) + 1
                self._cleanup_failures[session_id] = failures
                expiry_task = self._expiry_tasks.get(session_id)
                if expiry_task is not None and expiry_task is not asyncio.current_task():
                    expiry_task.cancel()
                self._expiry_tasks[session_id] = asyncio.create_task(
                    self._retry_cleanup(session_id, failures),
                    name=f"camera-media-cleanup:{session_id}",
                )
                raise
            self._sessions.pop(session_id, None)
            self._cleanup_failures.pop(session_id, None)
            expiry_task = self._expiry_tasks.pop(session_id, None)
            if expiry_task is not None and expiry_task is not asyncio.current_task():
                expiry_task.cancel()
            return True

    async def close_all(self) -> None:
        failures: list[str] = []
        for session_id in list(self._sessions):
            try:
                await self.close(session_id)
            except CameraMediaCleanupError:
                failures.append(session_id)
        if failures:
            raise CameraMediaCleanupError(
                f"failed to clean up {len(failures)} camera media session(s)"
            )

    async def _expire_after(self, session_id: str, timeout_seconds: int) -> None:
        try:
            await asyncio.sleep(timeout_seconds)
            await self.close(session_id)
        except (asyncio.CancelledError, CameraMediaCleanupError):
            return

    async def _retry_cleanup(self, session_id: str, failure_count: int) -> None:
        try:
            await asyncio.sleep(min(2 ** min(failure_count - 1, 5), 30))
            await self.close(session_id)
        except (asyncio.CancelledError, CameraMediaCleanupError):
            return

    async def _expire_locked(self) -> None:
        now = datetime.now(UTC)
        expired = [item for item in self._sessions.values() if item.expires_at <= now]
        for active in expired:
            if active.session_id in self._cleanup_failures:
                continue
            try:
                await self._remove_stream(active.stream_name)
            except CameraMediaCleanupError:
                failures = self._cleanup_failures.get(active.session_id, 0) + 1
                self._cleanup_failures[active.session_id] = failures
                self._expiry_tasks[active.session_id] = asyncio.create_task(
                    self._retry_cleanup(active.session_id, failures),
                    name=f"camera-media-cleanup:{active.session_id}",
                )
                continue
            self._sessions.pop(active.session_id, None)
            self._cleanup_failures.pop(active.session_id, None)
            expiry_task = self._expiry_tasks.pop(active.session_id, None)
            if expiry_task is not None and expiry_task is not asyncio.current_task():
                expiry_task.cancel()

    async def _remove_stream(self, stream_name: str) -> None:
        try:
            await asyncio.wait_for(self.client.remove_stream(stream_name), timeout=5.0)
        except (Go2RtcError, TimeoutError, OSError) as exc:
            raise CameraMediaCleanupError("camera media session cleanup failed") from exc


class CameraMediaCapacityError(RuntimeError):
    pass


class CameraSourceUnavailableError(RuntimeError):
    pass


class CameraMediaCleanupError(RuntimeError):
    pass


media_session_broker = CameraMediaSessionBroker()
