from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .schemas import WyzeBridgeConfig
from .settings import UPSTREAM_CONTROL_URL, host_rtsp_port


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
        self._lock = asyncio.Lock()
        self._last_error: str | None = None

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
            try:
                self._process = await asyncio.create_subprocess_exec(
                    "flask",
                    "run",
                    "--host=127.0.0.1",
                    "--port=5000",
                    env=self._bridge_environment(config, runtime_config),
                )
            except OSError as exc:
                self._last_error = "The embedded Wyze bridge could not be started."
                raise BridgeUnavailableError(self._last_error) from exc
            self._config = runtime_config
            self._last_error = None

    async def stop(self) -> None:
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._config = None
        if process is None or process.returncode is not None:
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
            "state": (
                "running"
                if self.running
                else "starting"
                if self.configured
                else "awaiting_configuration"
            ),
            "last_error": self._last_error,
            "rtsp_host_port": host_rtsp_port(),
        }

    async def cameras(self) -> list[dict[str, Any]]:
        config = self._config
        if config is None or not self.running:
            raise BridgeUnavailableError("The Wyze bridge is not configured and running.")
        try:
            async with httpx.AsyncClient(
                timeout=8.0,
                auth=httpx.BasicAuth(config.web_username, config.web_password),
            ) as client:
                response = await client.get(f"{UPSTREAM_CONTROL_URL}/api")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._last_error = "The embedded Wyze bridge is still connecting."
            raise BridgeUnavailableError(self._last_error) from exc

        cameras = self._normalize_cameras(payload)
        if config.enabled_camera_names:
            allowed = {name.casefold() for name in config.enabled_camera_names}
            cameras = [camera for camera in cameras if camera["name"].casefold() in allowed]
        return [self._with_source_url(camera, config) for camera in cameras]

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
        raw_cameras = payload.get("cameras", payload) if isinstance(payload, Mapping) else payload
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
                    "online": str(item.get("status") or "").lower()
                    not in {"offline", "error", "unavailable"},
                }
            )
        return normalized

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
                f"{config.advertised_host}:{host_rtsp_port()}/{stream_id}"
            ),
        }


bridge_supervisor = WyzeBridgeSupervisor()
