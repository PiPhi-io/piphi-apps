from __future__ import annotations

import asyncio
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .go2rtc import (
    Go2RtcClient,
    Go2RtcError,
    Go2RtcSnapshotTooLargeError,
    go2rtc,
    validate_source_url,
)

MAX_ANALYSIS_MEDIA_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})


@dataclass(frozen=True)
class IssuedAnalysisMedia:
    media_ref: str
    expires_at: datetime


@dataclass(frozen=True)
class AnalysisMedia:
    content_type: str
    content: bytes


@dataclass
class _StoredAnalysisMedia:
    content_type: str
    content: bytearray
    expires_at: datetime


class AnalysisMediaBroker:
    """Owns bounded, one-time image references and never persists image content."""

    def __init__(
        self,
        client: Go2RtcClient | None = None,
        *,
        capacity: int | None = None,
        byte_capacity: int | None = None,
    ) -> None:
        self.client = client or go2rtc
        self.capacity = capacity or max(1, int(os.getenv("PIPHI_ANALYSIS_MEDIA_CAPACITY", "32")))
        self.byte_capacity = byte_capacity or max(
            MAX_ANALYSIS_MEDIA_BYTES,
            int(os.getenv("PIPHI_ANALYSIS_MEDIA_BYTE_CAPACITY", str(64 * 1024 * 1024))),
        )
        self._items: dict[str, _StoredAnalysisMedia] = {}
        self._expiry_tasks: dict[str, asyncio.Task[None]] = {}
        self._cleanup_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_issues = 0
        self._stored_bytes = 0
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        return len(self._items)

    @property
    def stored_bytes(self) -> int:
        return self._stored_bytes

    async def issue(self, *, source_url: str, ttl_seconds: int) -> IssuedAnalysisMedia:
        source = validate_source_url(source_url)
        await self._reserve_issue()
        try:
            content_type, content = await self._capture(source)
            normalized_type = _validate_image(content_type, content)
            return await self._store(normalized_type, content, ttl_seconds)
        finally:
            async with self._lock:
                self._pending_issues -= 1

    async def consume(self, media_ref: str) -> AnalysisMedia | None:
        async with self._lock:
            item = self._items.pop(media_ref, None)
            task = self._expiry_tasks.pop(media_ref, None)
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            if item is None:
                return None
            self._stored_bytes -= len(item.content)
            if item.expires_at <= datetime.now(UTC):
                _zero(item.content)
                return None
            content = bytes(item.content)
            _zero(item.content)
            return AnalysisMedia(content_type=item.content_type, content=content)

    async def revoke(self, media_ref: str) -> bool:
        async with self._lock:
            return self._remove_locked(media_ref)

    async def close_all(self) -> None:
        async with self._lock:
            for media_ref in list(self._items):
                self._remove_locked(media_ref)
        pending_streams = list(self._cleanup_tasks)
        for task in self._cleanup_tasks.values():
            task.cancel()
        self._cleanup_tasks.clear()
        failures = 0
        for stream_name in pending_streams:
            try:
                await asyncio.wait_for(self.client.remove_stream(stream_name), timeout=5.0)
            except (Go2RtcError, OSError, TimeoutError):
                failures += 1
        if failures:
            raise AnalysisMediaCleanupError(
                f"failed to clean up {failures} temporary analysis stream(s)"
            )

    async def _reserve_issue(self) -> None:
        async with self._lock:
            self._expire_locked()
            if (
                len(self._items) + self._pending_issues + len(self._cleanup_tasks)
                >= self.capacity
            ):
                raise AnalysisMediaCapacityError("analysis media item capacity has been reached")
            if (
                self._stored_bytes + (self._pending_issues + 1) * MAX_ANALYSIS_MEDIA_BYTES
                > self.byte_capacity
            ):
                raise AnalysisMediaCapacityError("analysis media byte capacity has been reached")
            self._pending_issues += 1

    async def _capture(self, source: str) -> tuple[str, bytes]:
        stream_name = f"piphi_analysis_{secrets.token_hex(16)}"
        try:
            await self.client.upsert_stream(stream_name, source)
            return await self.client.snapshot(stream_name)
        except Go2RtcSnapshotTooLargeError as exc:
            raise AnalysisMediaSizeError("snapshot exceeded 10 MiB") from exc
        except (Go2RtcError, OSError, TimeoutError) as exc:
            raise AnalysisMediaCaptureError("camera snapshot capture failed") from exc
        finally:
            try:
                await asyncio.wait_for(self.client.remove_stream(stream_name), timeout=5.0)
            except (Go2RtcError, OSError, TimeoutError) as exc:
                self._schedule_cleanup(stream_name)
                raise AnalysisMediaCleanupError("temporary analysis stream cleanup failed") from exc

    def _schedule_cleanup(self, stream_name: str) -> None:
        if stream_name in self._cleanup_tasks:
            return
        task = asyncio.create_task(
            self._retry_cleanup(stream_name),
            name="analysis-media-stream-cleanup",
        )
        self._cleanup_tasks[stream_name] = task

    async def _retry_cleanup(self, stream_name: str) -> None:
        delay = 1
        try:
            while True:
                await asyncio.sleep(delay)
                try:
                    await asyncio.wait_for(self.client.remove_stream(stream_name), timeout=5.0)
                except (Go2RtcError, OSError, TimeoutError):
                    delay = min(delay * 2, 30)
                    continue
                return
        except asyncio.CancelledError:
            return
        finally:
            self._cleanup_tasks.pop(stream_name, None)

    async def _store(
        self, content_type: str, content: bytes, ttl_seconds: int
    ) -> IssuedAnalysisMedia:
        buffer = bytearray(content)
        async with self._lock:
            self._expire_locked()
            if self._stored_bytes + len(buffer) > self.byte_capacity:
                _zero(buffer)
                raise AnalysisMediaCapacityError("analysis media byte capacity has been reached")
            media_ref = secrets.token_urlsafe(32)
            while media_ref in self._items:  # pragma: no cover - cryptographic collision defense
                media_ref = secrets.token_urlsafe(32)
            expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            self._items[media_ref] = _StoredAnalysisMedia(content_type, buffer, expires_at)
            self._stored_bytes += len(buffer)
            self._expiry_tasks[media_ref] = asyncio.create_task(
                self._expire_after(media_ref, ttl_seconds),
                name="analysis-media-expiry",
            )
            return IssuedAnalysisMedia(media_ref=media_ref, expires_at=expires_at)

    async def _expire_after(self, media_ref: str, ttl_seconds: int) -> None:
        try:
            await asyncio.sleep(ttl_seconds)
            await self.revoke(media_ref)
        except asyncio.CancelledError:
            return

    def _expire_locked(self) -> None:
        now = datetime.now(UTC)
        for media_ref, item in list(self._items.items()):
            if item.expires_at <= now:
                self._remove_locked(media_ref)

    def _remove_locked(self, media_ref: str) -> bool:
        item = self._items.pop(media_ref, None)
        task = self._expiry_tasks.pop(media_ref, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        if item is None:
            return False
        self._stored_bytes -= len(item.content)
        _zero(item.content)
        return True


def _validate_image(content_type: str, content: bytes) -> str:
    normalized = content_type.partition(";")[0].strip().lower()
    if normalized not in SUPPORTED_IMAGE_TYPES:
        raise AnalysisMediaTypeError("snapshot media type is not supported")
    if not content or len(content) > MAX_ANALYSIS_MEDIA_BYTES:
        raise AnalysisMediaSizeError("snapshot size is outside the supported range")
    signatures = {
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP",
    }
    if not signatures[normalized]:
        raise AnalysisMediaTypeError("snapshot content does not match its media type")
    return normalized


def _zero(content: bytearray) -> None:
    content[:] = b"\x00" * len(content)


class AnalysisMediaCapacityError(RuntimeError):
    pass


class AnalysisMediaCaptureError(RuntimeError):
    pass


class AnalysisMediaCleanupError(RuntimeError):
    pass


class AnalysisMediaSizeError(RuntimeError):
    pass


class AnalysisMediaTypeError(RuntimeError):
    pass


analysis_media_broker = AnalysisMediaBroker()
