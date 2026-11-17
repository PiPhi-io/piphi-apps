from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from time import monotonic
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


def _safe_native_eof_detail(response: httpx.Response) -> str | None:
    return "EOF" if response.text.strip().upper() == "EOF" else None


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

    async def _request(
        self,
        method: str,
        path: str,
        *,
        request_timeout: float,
        operation: str,
        **kwargs,
    ) -> httpx.Response:
        try:
            async with self._client(request_timeout) as client:
                return await client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.HTTPError:
            raise Go2RtcError(f"go2rtc {operation} request failed") from None

    async def health(self) -> dict[str, object]:
        response = await self._request("GET", "/api", request_timeout=3.0, operation="health")
        if response.status_code != 200:
            raise Go2RtcError(f"go2rtc health failed with status {response.status_code}")
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

    async def upsert_ffmpeg_stream(
        self,
        name: str,
        source_url: str,
        *,
        include_audio: bool = False,
    ) -> None:
        """Relay through FFmpeg without changing camera codecs."""
        source = validate_source_url(source_url)
        parsed = urlsplit(source)
        source_without_fragment = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        await self._upsert_stream(
            name,
            f"ffmpeg:{source_without_fragment}#video=copy#audio={'opus' if include_audio else '0'}",
        )

    async def upsert_browser_compatible_ffmpeg_stream(
        self,
        name: str,
        source_url: str,
        *,
        include_audio: bool = False,
    ) -> None:
        """Transcode video only after copied H.264 cannot match the WebRTC offer."""
        source = validate_source_url(source_url)
        parsed = urlsplit(source)
        source_without_fragment = urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
        )
        await self._upsert_stream(
            name,
            f"ffmpeg:{source_without_fragment}#video=h264#audio={'opus' if include_audio else '0'}",
        )

    async def _upsert_stream(self, name: str, source: str) -> None:
        response = await self._request(
            "PUT",
            "/api/streams",
            request_timeout=8.0,
            operation="stream configuration",
            params={"name": name, "src": source},
        )
        if response.status_code not in {200, 201, 204}:
            raise Go2RtcError(
                f"go2rtc stream configuration failed with status {response.status_code}"
            )

    async def remove_stream(self, name: str) -> None:
        response = await self._request(
            "DELETE",
            "/api/streams",
            request_timeout=5.0,
            operation="stream removal",
            params={"src": name},
        )
        if response.status_code not in {200, 202, 204, 404}:
            raise Go2RtcError(f"go2rtc stream removal failed with status {response.status_code}")

    async def exchange_offer(self, name: str, sdp: str) -> str:
        response = await self._request(
            "POST",
            "/api/webrtc",
            request_timeout=12.0,
            operation="WebRTC exchange",
            params={"src": name},
            headers={"content-type": "application/json"},
            json={"type": "offer", "sdp": sdp},
        )
        if response.status_code not in {200, 201}:
            detail = _safe_native_eof_detail(response)
            raise Go2RtcError(
                f"go2rtc WebRTC exchange failed with status {response.status_code}",
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
        response = await self._request(
            "GET",
            "/api/frame.jpeg",
            request_timeout=10.0,
            operation="snapshot",
            params={"src": name},
        )
        if response.status_code != 200:
            raise Go2RtcError(f"go2rtc snapshot failed with status {response.status_code}")
        if len(response.content) > 8 * 1024 * 1024:
            raise Go2RtcError("go2rtc snapshot exceeded 8 MiB")
        return response.headers.get("content-type", "image/jpeg"), response.content


class Go2RtcProcess:
    def __init__(self) -> None:
        self.process: asyncio.subprocess.Process | None = None
        self.state = "stopped"
        self.last_error: str | None = None
        self.restart_count = 0
        self._monitor_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._binary: Path | None = None
        self._config: str | None = None

    async def start(self) -> None:
        if os.getenv("GO2RTC_MANAGED", "true").lower() not in {"1", "true", "yes"}:
            self.state = "external"
            return
        binary = Path(os.getenv("GO2RTC_BINARY", "/usr/local/bin/go2rtc"))
        if not await asyncio.to_thread(binary.is_file):
            if os.getenv("PIPHI_ENV", "development").lower() == "production":
                raise RuntimeError(f"go2rtc binary not found: {binary}")
            self.state = "stopped"
            return
        self._binary = binary
        self._config = os.getenv("GO2RTC_CONFIG", "/etc/piphi/go2rtc.yaml")
        self._stopping = False
        await self._spawn_and_wait_ready()
        self._monitor_task = asyncio.create_task(self._monitor(), name="go2rtc-supervisor")

    async def _spawn_and_wait_ready(self) -> None:
        if self._binary is None or self._config is None:
            raise RuntimeError("go2rtc process configuration is unavailable")
        self.state = "starting"
        self.process = await asyncio.create_subprocess_exec(
            str(self._binary),
            "-config",
            self._config,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT,
        )
        client = Go2RtcClient()
        deadline = monotonic() + _startup_timeout_seconds()
        while monotonic() < deadline:
            if self.process.returncode is not None:
                self.state = "degraded"
                self.last_error = "go2rtc exited before readiness"
                raise RuntimeError(
                    f"go2rtc exited during startup with code {self.process.returncode}"
                )
            try:
                await client.health()
                self.state = "running"
                self.last_error = None
                return
            except (Go2RtcError, httpx.HTTPError):
                await asyncio.sleep(0.1)
        await self._terminate_process(self.process)
        self.state = "degraded"
        self.last_error = "go2rtc readiness deadline exceeded"
        raise RuntimeError("go2rtc did not become ready before the startup deadline")

    async def _monitor(self) -> None:
        while not self._stopping and self.process is not None:
            process = self.process
            returncode = await process.wait()
            if self._stopping or process is not self.process:
                return
            self.state = "degraded"
            self.last_error = f"go2rtc exited unexpectedly ({returncode})"
            while not self._stopping:
                self.restart_count += 1
                if self.restart_count > _max_restart_attempts():
                    self.state = "failed"
                    self.last_error = "go2rtc exceeded its restart limit"
                    return
                await asyncio.sleep(min(2 ** (self.restart_count - 1), 30))
                try:
                    await self._spawn_and_wait_ready()
                except (OSError, RuntimeError):
                    continue
                break

    async def stop(self) -> None:
        self._stopping = True
        process = self.process
        if process is not None:
            await self._terminate_process(process)
        monitor_task = self._monitor_task
        self._monitor_task = None
        if monitor_task is not None and monitor_task is not asyncio.current_task():
            with suppress(asyncio.CancelledError):
                await monitor_task
        self.process = None
        self.state = "stopped"

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
            await process.wait()


def _startup_timeout_seconds() -> float:
    try:
        return max(5.0, min(float(os.getenv("GO2RTC_STARTUP_TIMEOUT_SECONDS", "15")), 30.0))
    except ValueError:
        return 15.0


def _max_restart_attempts() -> int:
    try:
        return max(0, min(int(os.getenv("GO2RTC_MAX_RESTART_ATTEMPTS", "5")), 20))
    except ValueError:
        return 5


go2rtc = Go2RtcClient()
go2rtc_process = Go2RtcProcess()
