from __future__ import annotations

from importlib import import_module
from typing import Any

SAFE_FEATURES = {
    "battery",
    "floodLight",
    "ir_lights",
    "ptz",
    "siren",
    "siren_play",
    "snapshot",
    "status_led",
    "stream",
}


def _text(value: Any, fallback: str = "Unknown") -> str:
    normalized = str(value or "").strip()
    return normalized if normalized and normalized.upper() != "UNKNOWN" else fallback


class ReolinkClient:
    """Narrow adapter around reolink_aio so runtime tests never require hardware."""

    def __init__(self, host: Any) -> None:
        self._host = host

    @classmethod
    async def connect(
        cls,
        *,
        host: str,
        username: str,
        password: str,
        port: int | None = None,
        use_https: bool | None = None,
        timeout: int = 20,
    ) -> ReolinkClient:
        host_type = import_module("reolink_aio.api").Host
        upstream = host_type(
            host=host,
            username=username,
            password=password,
            port=port,
            use_https=use_https,
            timeout=timeout,
        )
        try:
            await upstream.get_host_data()
            await upstream.get_states()
        except Exception:
            await upstream.logout()
            raise
        return cls(upstream)

    async def refresh(self) -> dict[str, Any]:
        await self._host.get_states()
        return self.snapshot()

    async def close(self) -> None:
        await self._host.logout()

    def snapshot(self) -> dict[str, Any]:
        channels = [self._channel_snapshot(channel) for channel in self._host.channels]
        return {
            "connected": True,
            "camera_count": len(channels),
            "name": _text(self._host.nvr_name, "Reolink device"),
            "model": _text(self._host.model),
            "is_nvr": bool(self._host.is_nvr),
            "channels": channels,
        }

    def _channel_snapshot(self, channel: int) -> dict[str, Any]:
        feature_set = set(self._host.capabilities.get(channel, {}).get(None, set()))
        return {
            "channel": channel,
            "name": _text(self._host.camera_name(channel), f"Camera {channel + 1}"),
            "model": _text(self._host.camera_model(channel)),
            "firmware": _text(self._host.camera_sw_version(channel)),
            "online": bool(self._host.camera_online(channel)),
            "is_doorbell": bool(self._host.is_doorbell(channel)),
            "features": sorted(feature_set & SAFE_FEATURES),
        }
