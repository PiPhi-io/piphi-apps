from __future__ import annotations

import hashlib
import logging
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

logger = logging.getLogger(__name__)


def _text(value: Any, fallback: str = "Unknown") -> str:
    normalized = str(value or "").strip()
    return normalized if normalized and normalized.upper() != "UNKNOWN" else fallback


def _stable_hash(value: Any) -> str | None:
    normalized = str(value or "").strip()
    if not normalized or normalized.upper() == "UNKNOWN":
        return None
    return hashlib.sha256(normalized.casefold().encode()).hexdigest()[:24]


def _safe(callable_or_value: Any, *args: Any) -> Any:
    try:
        return callable_or_value(*args) if callable(callable_or_value) else callable_or_value
    except Exception:  # noqa: BLE001 - optional upstream getters vary by model
        return None


class ReolinkSetupError(RuntimeError):
    """A sanitized, actionable setup failure safe to return to Core."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _setup_error_code(exc: Exception) -> str:
    name = type(exc).__name__
    if name in {"CredentialsInvalidError", "LoginError"}:
        return "invalid_auth"
    if name == "LoginAccountDeviceError":
        return "account_device_unsupported"
    if name == "LoginFirmwareError":
        return "firmware_update_required"
    if name == "LoginPrivacyModeError":
        return "privacy_mode_enabled"
    if name in {"InvalidParameterError", "NotSupportedError"}:
        return "unsupported_device"
    if name in {"ReolinkTimeoutError", "TimeoutError"}:
        return "connection_timeout"
    return "cannot_connect"


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
            client = cls(upstream)
            snapshot = client.snapshot()
            if not snapshot["hardware_id"]:
                raise ReolinkSetupError("stable_identity_unavailable")
            return client
        except Exception as exc:
            try:
                await upstream.logout()
            except Exception as logout_exc:  # noqa: BLE001 - setup cleanup must complete
                logger.debug("reolink_setup_logout_failed error=%s", type(logout_exc).__name__)
            if isinstance(exc, ReolinkSetupError):
                raise
            raise ReolinkSetupError(_setup_error_code(exc)) from exc

    async def refresh(self) -> dict[str, Any]:
        await self._host.get_states()
        return self.snapshot()

    async def close(self) -> None:
        await self._host.logout()

    def snapshot(self) -> dict[str, Any]:
        channels = [self._channel_snapshot(channel) for channel in self._host.channels]
        try:
            mac_address = self._host.mac_address
        except Exception:  # noqa: BLE001 - MAC is optional on some models
            mac_address = None
        hardware_id = _stable_hash(mac_address)
        hardware_id = hardware_id or _stable_hash(_safe(lambda: self._host.uid))
        return {
            "connected": True,
            "camera_count": len(channels),
            "name": _text(self._host.nvr_name, "Reolink device"),
            "model": _text(self._host.model),
            "hardware": _text(_safe(lambda: self._host.hardware_version)),
            "firmware": _text(_safe(lambda: self._host.sw_version)),
            "hardware_id": hardware_id,
            "is_nvr": bool(self._host.is_nvr),
            "is_battery": bool(getattr(self._host, "is_battery", False)),
            "channels": channels,
        }

    def _channel_snapshot(self, channel: int) -> dict[str, Any]:
        feature_set = set(self._host.capabilities.get(channel, {}).get(None, set()))
        return {
            "channel": channel,
            "hardware_id": _stable_hash(_safe(getattr(self._host, "camera_uid", None), channel)),
            "name": _text(self._host.camera_name(channel), f"Camera {channel + 1}"),
            "model": _text(self._host.camera_model(channel)),
            "hardware": _text(
                _safe(getattr(self._host, "camera_hardware_version", None), channel)
            ),
            "firmware": _text(self._host.camera_sw_version(channel)),
            "online": bool(self._host.camera_online(channel)),
            "sleeping": bool(_safe(getattr(self._host, "sleeping", None), channel)),
            "is_doorbell": bool(self._host.is_doorbell(channel)),
            "features": sorted(feature_set & SAFE_FEATURES),
        }
