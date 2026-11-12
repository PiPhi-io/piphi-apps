from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx


class Go2RtcError(RuntimeError):
    """Raised when the private go2rtc control plane rejects a request."""

    def __init__(
        self,
        message: str,
        *,
        operation: str | None = None,
        status_code: int | None = None,
        response_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status_code = status_code
        self.response_detail = response_detail

    @property
    def is_native_source_eof(self) -> bool:
        return (
            self.operation == "webrtc_exchange"
            and self.status_code == 500
            and (self.response_detail or "").strip().upper() == "EOF"
        )


_CAMERA_SOURCE_PATTERN = re.compile(r"(?i)\brtsps?://[^\s\"']+")


def _safe_response_detail(response: httpx.Response) -> str:
    detail = " ".join(response.text.strip().split())
    return _CAMERA_SOURCE_PATTERN.sub("<camera-source>", detail)[:300]


def _safe_response_error(response: httpx.Response) -> str:
    detail = _safe_response_detail(response)
    if not detail:
        return f"status {response.status_code}"
    return f"status {response.status_code}: {detail}"


def validate_source_url(value: str) -> str:
    source = value.strip()
    if not source or len(source) > 4096 or any(char in source for char in "\r\n\0"):
        raise ValueError("source_url must be a non-empty camera URL")
    parsed = urlsplit(source)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
        raise ValueError("source_url must use rtsp:// or rtsps:// and include a host")
    return source


def stream_name_for(config_id: str) -> str:
    normalized = "".join(char if char.isalnum() else "_" for char in config_id.lower()).strip("_")
    if not normalized:
        raise ValueError("config_id must contain an alphanumeric character")
    return f"piphi_{normalized[:96]}"


class Go2RtcClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("GO2RTC_URL", "http://127.0.0.1:1984")).rstrip("/")
        self.transport = transport

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self.transport)

    async def health(self) -> dict[str, object]:
        async with self._client(3.0) as client:
            response = await client.get(f"{self.base_url}/api")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise Go2RtcError("go2rtc returned an invalid health response") from exc
        if not isinstance(payload, Mapping):
            raise Go2RtcError("go2rtc returned an invalid health response")
        return dict(payload)

    async def upsert_stream(self, name: str, source_url: str) -> None:
        source = validate_source_url(source_url)
        await self._upsert_stream(name, source)

    async def upsert_ffmpeg_stream(self, name: str, source_url: str) -> None:
        """Relay through FFmpeg without changing camera codecs."""
        source = validate_source_url(source_url)
        parsed = urlsplit(source)
        source_without_fragment = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        await self._upsert_stream(
            name,
            f"ffmpeg:{source_without_fragment}#video=copy#audio=copy",
        )

    async def upsert_browser_compatible_ffmpeg_stream(self, name: str, source_url: str) -> None:
        """Transcode video only after copied H.264 cannot match the WebRTC offer."""
        source = validate_source_url(source_url)
        parsed = urlsplit(source)
        source_without_fragment = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        await self._upsert_stream(
            name,
            f"ffmpeg:{source_without_fragment}#video=h264#audio=copy",
        )

    async def _upsert_stream(self, name: str, source: str) -> None:
        async with self._client(8.0) as client:
            response = await client.put(
                f"{self.base_url}/api/streams",
                params={"name": name, "src": source},
            )
        if response.status_code not in {200, 201, 204}:
            raise Go2RtcError(
                f"go2rtc stream configuration failed with status {response.status_code}"
            )

    async def remove_stream(self, name: str) -> None:
        async with self._client(5.0) as client:
            response = await client.delete(f"{self.base_url}/api/streams", params={"src": name})
        if response.status_code not in {200, 202, 204, 404}:
            raise Go2RtcError(f"go2rtc stream removal failed with status {response.status_code}")

    async def exchange_offer(self, name: str, sdp: str) -> str:
        async with self._client(12.0) as client:
            response = await client.post(
                f"{self.base_url}/api/webrtc",
                params={"src": name},
                headers={"content-type": "application/json"},
                json={"type": "offer", "sdp": sdp},
            )
        if response.status_code not in {200, 201}:
            detail = _safe_response_detail(response)
            raise Go2RtcError(
                f"go2rtc WebRTC exchange failed with {_safe_response_error(response)}",
                operation="webrtc_exchange",
                status_code=response.status_code,
                response_detail=detail,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise Go2RtcError("go2rtc returned an invalid WebRTC answer") from exc
        answer = str(payload.get("sdp") or "") if isinstance(payload, Mapping) else ""
        if not answer:
            raise Go2RtcError("go2rtc returned an invalid WebRTC answer")
        return answer

    async def snapshot(self, name: str) -> tuple[str, bytes]:
        async with self._client(10.0) as client:
            response = await client.get(f"{self.base_url}/api/frame.jpeg", params={"src": name})
        if response.status_code != 200:
            raise Go2RtcError(f"go2rtc snapshot failed with status {response.status_code}")
        if len(response.content) > 8 * 1024 * 1024:
            raise Go2RtcError("go2rtc snapshot exceeded 8 MiB")
        return response.headers.get("content-type", "image/jpeg"), response.content


class Go2RtcProcess:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None

    async def start(self) -> None:
        if os.getenv("GO2RTC_MANAGED", "true").lower() not in {"1", "true", "yes"}:
            return
        binary = Path(os.getenv("GO2RTC_BINARY", "/usr/local/bin/go2rtc"))
        if not await asyncio.to_thread(binary.is_file):
            if os.getenv("PIPHI_ENV", "development").lower() == "production":
                raise RuntimeError(f"go2rtc binary not found: {binary}")
            return
        config = os.getenv("GO2RTC_CONFIG", "/etc/piphi/go2rtc.yaml")
        self.process = await asyncio.create_subprocess_exec(
            str(binary),
            "-config",
            config,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT,
        )
        client = Go2RtcClient()
        for _ in range(50):
            if self.process.returncode is not None:
                raise RuntimeError(
                    f"go2rtc exited during startup with code {self.process.returncode}"
                )
            try:
                await client.health()
                return
            except (Go2RtcError, httpx.HTTPError):
                await asyncio.sleep(0.1)
        await self.stop()
        raise RuntimeError("go2rtc did not become ready within 5 seconds")

    async def stop(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), timeout=5.0)
        except TimeoutError:
            self.process.kill()
            await self.process.wait()


go2rtc = Go2RtcClient()
go2rtc_process = Go2RtcProcess()
