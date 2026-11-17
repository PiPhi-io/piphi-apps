from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .schemas import WyzeBridgeConfig
from .settings import INTERNAL_RTSP_PORT, UPSTREAM_CONTROL_URL, rtsp_service_port


class BridgeUnavailableError(RuntimeError):
    """Raised when the private upstream bridge cannot serve a request."""


@dataclass(frozen=True)
class BridgeRuntimeConfig:
    advertised_host: str
    enabled_camera_names: tuple[str, ...]
    stream_password: str
    web_username: str
    web_password: str


class WyzeBridgeSupervisor:
    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._config: BridgeRuntimeConfig | None = None
        self._source_config: WyzeBridgeConfig | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._state = "awaiting_configuration"
        self._last_error: str | None = None
        self._restart_count = 0

    @property
    def configured(self) -> bool:
        return self._config is not None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def configure(self, config: WyzeBridgeConfig) -> None:
        async with self._lock:
            await self._stop_locked()
            runtime_config = BridgeRuntimeConfig(
                advertised_host=config.advertised_host,
                enabled_camera_names=tuple(config.enabled_camera_names),
                stream_password=secrets.token_urlsafe(32),
                web_username="piphi",
                web_password=secrets.token_urlsafe(32),
            )
            self._source_config = config
            self._config = runtime_config
            self._state = "starting"
            self._restart_count = 0
            try:
                await self._start_locked(config, runtime_config)
            except BridgeUnavailableError:
                failure = self._last_error
                await self._stop_locked()
                self._state = "degraded"
                self._last_error = failure
                raise
            self._monitor_task = asyncio.create_task(
                self._monitor_process(),
                name="wyze-bridge-supervisor",
            )

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        monitor_task = self._monitor_task
        self._monitor_task = None
        if monitor_task is not None and monitor_task is not asyncio.current_task():
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task
        process = self._process
        self._process = None
        self._config = None
        self._source_config = None
        self._state = "stopped"
        self._restart_count = 0
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def _start_locked(
        self,
        source_config: WyzeBridgeConfig,
        runtime_config: BridgeRuntimeConfig,
    ) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                "flask",
                "run",
                "--host=127.0.0.1",
                "--port=5000",
                env=self._bridge_environment(source_config, runtime_config),
            )
        except OSError as exc:
            self._state = "failed"
            self._last_error = "The embedded Wyze bridge could not be started."
            raise BridgeUnavailableError(self._last_error) from exc

        self._process = process
        self._state = "starting"
        try:
            await self._wait_until_ready(process, runtime_config)
        except BridgeUnavailableError:
            await self._terminate_process(process)
            if self._process is process:
                self._process = None
            raise
        self._state = "running"
        self._last_error = None

    async def _wait_until_ready(
        self,
        process: asyncio.subprocess.Process,
        runtime_config: BridgeRuntimeConfig,
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _readiness_timeout_seconds()
        while loop.time() < deadline:
            if process.returncode is not None:
                self._state = "degraded"
                self._last_error = "The embedded Wyze bridge exited before it became ready."
                raise BridgeUnavailableError(self._last_error)
            try:
                await self._request_camera_payload(runtime_config, timeout=2.0)
                await self._probe_rtsp_listener(timeout=2.0)
            except (httpx.HTTPError, ValueError):
                await asyncio.sleep(0.25)
                continue
            return
        self._state = "degraded"
        self._last_error = "The embedded Wyze bridge did not become ready in time."
        raise BridgeUnavailableError(self._last_error)

    async def _monitor_process(self) -> None:
        while True:
            process = self._process
            if process is None:
                return
            returncode = await process.wait()
            async with self._lock:
                if (
                    process is not self._process
                    or self._source_config is None
                    or self._config is None
                ):
                    return
                self._process = None
                self._state = "degraded"
                self._last_error = f"The embedded Wyze bridge exited unexpectedly ({returncode})."

            while True:
                self._restart_count += 1
                if self._restart_count > _max_restart_attempts():
                    self._state = "failed"
                    self._last_error = "The embedded Wyze bridge exceeded its restart limit."
                    return
                await asyncio.sleep(min(2 ** (self._restart_count - 1), 30))
                async with self._lock:
                    source_config = self._source_config
                    runtime_config = self._config
                    if source_config is None or runtime_config is None:
                        return
                    try:
                        await self._start_locked(source_config, runtime_config)
                    except BridgeUnavailableError:
                        continue
                    break

    @staticmethod
    async def _terminate_process(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
        except TimeoutError:
            process.kill()
            await process.wait()

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "running": self.running,
            "state": self._state,
            "last_error": self._last_error,
            "restart_count": self._restart_count,
            "rtsp_service_port": rtsp_service_port(),
        }

    async def cameras(self) -> list[dict[str, Any]]:
        config = self._config
        if config is None or not self.running or self._state != "running":
            raise BridgeUnavailableError("The Wyze bridge is not configured and running.")
        try:
            payload = await self._request_camera_payload(config, timeout=8.0)
        except (httpx.HTTPError, ValueError) as exc:
            self._state = "degraded"
            self._last_error = "The embedded Wyze bridge is not responding."
            raise BridgeUnavailableError(self._last_error) from exc

        self._state = "running"
        self._last_error = None

        cameras = self._normalize_cameras(payload)
        if config.enabled_camera_names:
            allowed = {name.casefold() for name in config.enabled_camera_names}
            cameras = [camera for camera in cameras if camera["name"].casefold() in allowed]
        return [self._with_source_url(camera, config) for camera in cameras]

    @staticmethod
    async def _request_camera_payload(
        config: BridgeRuntimeConfig,
        *,
        timeout: float,
    ) -> object:
        async with httpx.AsyncClient(
            timeout=timeout,
            auth=httpx.BasicAuth(config.web_username, config.web_password),
        ) as client:
            response = await client.get(f"{UPSTREAM_CONTROL_URL}/api")
        response.raise_for_status()
        payload = response.json()
        WyzeBridgeSupervisor._camera_items(payload)
        return payload

    @staticmethod
    async def _probe_rtsp_listener(*, timeout: float) -> None:
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", INTERNAL_RTSP_PORT),
                timeout=timeout,
            )
        except (OSError, TimeoutError) as exc:
            raise ValueError("Wyze RTSP listener is unavailable") from exc
        writer.close()
        await writer.wait_closed()

    @staticmethod
    def _bridge_environment(
        config: WyzeBridgeConfig,
        runtime_config: BridgeRuntimeConfig,
    ) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                "WYZE_EMAIL": config.wyze_email,
                "WYZE_PASSWORD": config.wyze_password.get_secret_value(),
                "API_ID": config.api_id.get_secret_value(),
                "API_KEY": config.api_key.get_secret_value(),
                "WB_AUTH": "true",
                "WB_USERNAME": runtime_config.web_username,
                "WB_PASSWORD": runtime_config.web_password,
                "WB_API": runtime_config.stream_password,
                "ON_DEMAND": "true",
                "RECORD_ALL": "false",
            }
        )
        if config.enabled_camera_names:
            env["FILTER_NAMES"] = ",".join(config.enabled_camera_names)
        return env

    @staticmethod
    def _normalize_cameras(payload: object) -> list[dict[str, Any]]:
        try:
            raw_cameras = WyzeBridgeSupervisor._camera_items(payload)
        except ValueError:
            return []
        if isinstance(raw_cameras, Mapping):
            items = [
                ({"name_uri": key, **value} if isinstance(value, Mapping) else {"name_uri": key})
                for key, value in raw_cameras.items()
            ]
        elif isinstance(raw_cameras, list):
            items = [item for item in raw_cameras if isinstance(item, Mapping)]
        else:
            return []

        normalized = []
        for item in items:
            stream_id = str(
                item.get("name_uri") or item.get("uri") or item.get("stream") or ""
            ).strip(" /")
            name = str(item.get("nickname") or item.get("name") or stream_id).strip()
            if not stream_id or not name:
                continue
            normalized.append(
                {
                    "id": stream_id,
                    "name": name,
                    "model": str(item.get("product_model") or item.get("model") or "").strip()
                    or None,
                    "online": str(item.get("status") or "").strip().lower()
                    in {"connected", "online", "streaming"},
                }
            )
        return normalized

    @staticmethod
    def _camera_items(payload: object) -> Mapping[Any, Any] | list[Any]:
        if isinstance(payload, Mapping) and "cameras" in payload:
            raw_cameras = payload["cameras"]
        else:
            raw_cameras = payload
        if isinstance(raw_cameras, list):
            if not all(isinstance(item, Mapping) for item in raw_cameras):
                raise ValueError("Wyze bridge returned an invalid camera list")
            return raw_cameras
        if isinstance(raw_cameras, Mapping):
            if raw_cameras and not all(isinstance(item, Mapping) for item in raw_cameras.values()):
                raise ValueError("Wyze bridge returned an invalid camera mapping")
            if not raw_cameras and not (isinstance(payload, Mapping) and "cameras" in payload):
                raise ValueError("Wyze bridge returned an ambiguous empty response")
            return raw_cameras
        raise ValueError("Wyze bridge returned an invalid camera response")

    @staticmethod
    def _with_source_url(
        camera: dict[str, Any],
        config: BridgeRuntimeConfig,
    ) -> dict[str, Any]:
        stream_id = quote(str(camera["id"]), safe="-._~")
        return {
            **camera,
            "source_url": (
                f"rtsp://wb:{quote(config.stream_password, safe='')}@"
                f"{config.advertised_host}:{rtsp_service_port()}/{stream_id}"
            ),
        }


bridge_supervisor = WyzeBridgeSupervisor()


def _readiness_timeout_seconds() -> float:
    try:
        return max(1.0, min(float(os.getenv("PIPHI_WYZE_READY_TIMEOUT_SECONDS", "45")), 120.0))
    except ValueError:
        return 45.0


def _max_restart_attempts() -> int:
    try:
        return max(0, min(int(os.getenv("PIPHI_WYZE_MAX_RESTART_ATTEMPTS", "5")), 20))
    except ValueError:
        return 5
