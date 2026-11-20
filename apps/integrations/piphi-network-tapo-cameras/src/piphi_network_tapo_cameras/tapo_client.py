from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class TapoSetupError(RuntimeError):
    """Sanitized transport failure safe to expose through the runtime API."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _error_code(exc: Exception) -> str:
    name = type(exc).__name__
    if name in {"AuthenticationError", "AuthenticationException"}:
        return "invalid_auth"
    if name in {"TimeoutError", "KasaTimeoutError"}:
        return "timeout"
    if name in {"UnsupportedDeviceError", "UnsupportedDeviceException"}:
        return "unsupported_device"
    return "unreachable"


def _stable_identity(raw: Any) -> str | None:
    value = str(raw or "").strip()
    if not value or value.upper() == "UNKNOWN":
        return None
    salt = os.getenv("PIPHI_IDENTITY_SALT", "piphi-network-tapo-cameras-v1")
    return hashlib.sha256(f"{salt}\0{value.casefold()}".encode()).hexdigest()[:32]


def _safe(value: Any, default: Any = None) -> Any:
    try:
        return value() if callable(value) else value
    except Exception:  # noqa: BLE001 - optional model attributes vary by firmware
        return default


@dataclass(frozen=True, slots=True)
class TapoSnapshot:
    hardware_id: str
    name: str
    model: str
    hardware: str | None
    firmware: str | None
    device_type: str
    privacy_mode: bool | None
    signal_strength: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "hardware_id": self.hardware_id,
            "name": self.name,
            "model": self.model,
            "hardware": self.hardware,
            "firmware": self.firmware,
            "device_type": self.device_type,
            "privacy_mode": self.privacy_mode,
            "signal_strength": self.signal_strength,
            "connected": True,
        }


class TapoClient:
    """Read-only adapter around python-kasa's SmartCam surface."""

    def __init__(self, device: Any) -> None:
        self._device = device

    @classmethod
    async def connect(cls, *, host: str, username: str, password: str) -> TapoClient:
        from kasa import Credentials, Discover

        credentials = Credentials(username=username, password=password)
        try:
            try:
                device = await Discover.discover_single(
                    host,
                    discovery_timeout=5,
                    timeout=10,
                    credentials=credentials,
                )
            except Exception as discovery_exc:
                if _error_code(discovery_exc) not in {"timeout", "unreachable"}:
                    raise
                device = await Discover.try_connect_all(
                    host,
                    timeout=10,
                    credentials=credentials,
                )
            if device is None:
                raise TapoSetupError("unreachable")
            client = cls(device)
            client.snapshot()
            return client
        except Exception as exc:
            if "device" in locals() and device is not None:
                try:
                    await device.disconnect()
                except Exception as cleanup_exc:  # noqa: BLE001 - third-party cleanup
                    logger.debug("tapo_disconnect_failed error=%s", type(cleanup_exc).__name__)
            if isinstance(exc, TapoSetupError):
                raise
            raise TapoSetupError(_error_code(exc)) from exc

    async def refresh(self) -> dict[str, Any]:
        try:
            await self._device.update()
            return self.snapshot().as_dict()
        except TapoSetupError:
            raise
        except Exception as exc:
            raise TapoSetupError(_error_code(exc)) from exc

    async def close(self) -> None:
        await self._device.disconnect()

    def snapshot(self) -> TapoSnapshot:
        from kasa import DeviceType, Module

        device_type = _safe(lambda: self._device.device_type)
        if device_type not in {DeviceType.Camera, DeviceType.Doorbell}:
            raise TapoSetupError("unsupported_device")
        if list(_safe(lambda: self._device.children, []) or []):
            raise TapoSetupError("child_or_hub_device_unsupported")
        modules = _safe(lambda: self._device.modules, {}) or {}
        battery_modules = {Module.BatterySensor, getattr(Module, "SmartCamBattery", None)}
        if any(module in modules for module in battery_modules if module is not None):
            raise TapoSetupError("battery_device_unsupported")
        hardware_id = _stable_identity(_safe(lambda: self._device.device_id))
        if hardware_id is None:
            raise TapoSetupError("stable_identity_unavailable")
        lens_mask = modules.get(Module.LensMask)
        privacy_value = None if lens_mask is None else _safe(lambda: lens_mask.enabled)
        privacy_mode = None if privacy_value is None else bool(privacy_value)
        hw_info = _safe(lambda: self._device.hw_info, {}) or {}
        if not isinstance(hw_info, dict):
            hw_info = {}
        rssi = _safe(lambda: self._device.rssi)
        return TapoSnapshot(
            hardware_id=hardware_id,
            name=str(_safe(lambda: self._device.alias, "Tapo camera") or "Tapo camera"),
            model=str(_safe(lambda: self._device.model, "Unknown") or "Unknown"),
            hardware=str(hw_info.get("hw_ver") or "") or None,
            firmware=str(hw_info.get("sw_ver") or hw_info.get("fw_ver") or "") or None,
            device_type=str(getattr(device_type, "value", device_type)),
            privacy_mode=privacy_mode,
            signal_strength=(
                int(rssi) if isinstance(rssi, int | float) and not isinstance(rssi, bool) else None
            ),
        )
