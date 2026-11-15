from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol


class RemoteV2UnavailableError(RuntimeError):
    """Raised when the optional Remote Protocol v2 client is unavailable."""


class RemoteV2CommandError(ValueError):
    """Raised when a command is outside the adapter's conservative allowlist."""


class RemoteV2AuthenticationError(RuntimeError):
    """Raised when stored Remote v2 credentials are no longer authorized."""


_LOGGER = logging.getLogger(__name__)
_PAIRING_PIN = re.compile(r"^[0-9A-Fa-f]{6}$")


@dataclass(frozen=True, slots=True)
class RemoteV2Device:
    """Stable identity and authenticated device metadata."""

    identity: str
    name: str
    manufacturer: str | None = None
    model: str | None = None
    software_version: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteV2Volume:
    level: int
    maximum: int
    muted: bool


@dataclass(frozen=True, slots=True)
class RemoteV2Snapshot:
    """A credential-free view of the latest protocol state."""

    available: bool
    authenticated: bool
    reauth_required: bool
    device: RemoteV2Device | None
    is_on: bool | None
    current_app: str | None
    volume: RemoteV2Volume | None


SnapshotCallback = Callable[[RemoteV2Snapshot], None]
RemoteFactory = Callable[..., Any]


class RemoteV2Client(Protocol):
    """Runtime-facing interface for an authenticated Android TV connection."""

    @property
    def snapshot(self) -> RemoteV2Snapshot: ...

    async def connect(self) -> RemoteV2Snapshot: ...

    async def generate_credentials(self) -> bool: ...

    async def start_pairing(self) -> tuple[str, str]: ...

    async def finish_pairing(self, pin: str) -> None: ...

    async def disconnect(self) -> None: ...

    async def refresh(self) -> RemoteV2Snapshot: ...

    async def send_key_command(self, key: str) -> None: ...

    def add_snapshot_callback(self, callback: SnapshotCallback) -> Callable[[], None]: ...


# Intentionally excludes text entry, app launching, long presses, and uncommon system keys.
SAFE_SHORT_KEYS = frozenset(
    {
        "BACK",
        "DPAD_CENTER",
        "DPAD_DOWN",
        "DPAD_LEFT",
        "DPAD_RIGHT",
        "DPAD_UP",
        "HOME",
        "MEDIA_FAST_FORWARD",
        "MEDIA_NEXT",
        "MEDIA_PAUSE",
        "MEDIA_PLAY",
        "MEDIA_PLAY_PAUSE",
        "MEDIA_PREVIOUS",
        "MEDIA_REWIND",
        "MEDIA_STOP",
        "POWER",
        "VOLUME_DOWN",
        "VOLUME_MUTE",
        "VOLUME_UP",
    }
)


def _default_remote_factory(**kwargs: Any) -> Any:
    try:
        remote_type = import_module("androidtvremote2").AndroidTVRemote
    except (ImportError, AttributeError) as exc:
        raise RemoteV2UnavailableError(
            "Android TV Remote Protocol v2 support is not installed"
        ) from exc
    return remote_type(**kwargs)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalized_mac(value: str) -> str:
    compact = "".join(character for character in value if character.isalnum()).upper()
    if len(compact) != 12 or any(character not in "0123456789ABCDEF" for character in compact):
        raise ValueError("Android TV returned an invalid MAC address")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


class AndroidTVRemoteV2Adapter:
    """Narrow async adapter around the optional ``androidtvremote2`` package."""

    def __init__(
        self,
        *,
        host: str,
        certfile: str,
        keyfile: str,
        client_name: str = "PiPhi Network",
        connect_timeout_seconds: float = 5.0,
        remote_factory: RemoteFactory | None = None,
    ) -> None:
        self._remote = (remote_factory or _default_remote_factory)(
            client_name=client_name,
            certfile=certfile,
            keyfile=keyfile,
            host=host,
            enable_ime=True,
            enable_voice=False,
        )
        self._connect_timeout_seconds = connect_timeout_seconds
        self._callbacks: list[SnapshotCallback] = []
        self._callbacks_registered = False
        self._available = False
        self._authenticated = False
        self._reauth_required = False
        self._device: RemoteV2Device | None = None
        self._is_on: bool | None = None
        self._current_app: str | None = None
        self._volume: RemoteV2Volume | None = None

    @property
    def snapshot(self) -> RemoteV2Snapshot:
        return RemoteV2Snapshot(
            available=self._available and self._authenticated,
            authenticated=self._authenticated,
            reauth_required=self._reauth_required,
            device=self._device,
            is_on=self._is_on,
            current_app=self._current_app,
            volume=self._volume,
        )

    def add_snapshot_callback(self, callback: SnapshotCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def remove() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return remove

    async def connect(self) -> RemoteV2Snapshot:
        if self._authenticated:
            return await self.refresh()
        self._register_callbacks()
        try:
            async with asyncio.timeout(self._connect_timeout_seconds):
                await self._remote.async_connect()
                name, mac_address = await self._remote.async_get_name_and_mac()
        except BaseException as exc:
            self._remote.disconnect()
            self._remove_callbacks()
            self._available = False
            self._authenticated = False
            self._emit_snapshot()
            if exc.__class__.__name__ == "InvalidAuth":
                raise RemoteV2AuthenticationError(
                    "Android TV pairing credentials are no longer authorized"
                ) from exc
            raise

        self._authenticated = True
        self._reauth_required = False
        self._available = True
        self._device = self._device_from_remote(name, mac_address)
        keep_reconnecting = getattr(self._remote, "keep_reconnecting", None)
        if callable(keep_reconnecting):
            keep_reconnecting(self._on_reauth_required)
        return await self.refresh()

    async def generate_credentials(self) -> bool:
        return bool(await self._remote.async_generate_cert_if_missing())

    async def start_pairing(self) -> tuple[str, str]:
        async with asyncio.timeout(self._connect_timeout_seconds):
            await self.generate_credentials()
            name, mac_address = await self._remote.async_get_name_and_mac()
            await self._remote.async_start_pairing()
        return _optional_text(name) or "Android TV", _normalized_mac(str(mac_address))

    async def finish_pairing(self, pin: str) -> None:
        if not _PAIRING_PIN.fullmatch(pin):
            raise ValueError("pairing PIN must be exactly six hexadecimal characters")
        async with asyncio.timeout(self._connect_timeout_seconds):
            await self._remote.async_finish_pairing(pin.upper())

    async def disconnect(self) -> None:
        self._remote.disconnect()
        self._remove_callbacks()
        self._available = False
        self._authenticated = False
        self._emit_snapshot()

    async def refresh(self) -> RemoteV2Snapshot:
        self._is_on = self._remote.is_on
        self._current_app = _optional_text(self._remote.current_app)
        self._volume = self._volume_from_remote(self._remote.volume_info)
        self._update_device_info()
        return self._emit_snapshot()

    async def send_key_command(self, key: str) -> None:
        normalized = key.strip().upper()
        if normalized.startswith("KEYCODE_"):
            normalized = normalized.removeprefix("KEYCODE_")
        if normalized not in SAFE_SHORT_KEYS:
            raise RemoteV2CommandError(f"Android TV key is not allowed: {key!r}")
        if not self.snapshot.available:
            raise RemoteV2UnavailableError("Android TV is not authenticated and available")
        self._remote.send_key_command(normalized, "SHORT")

    def _register_callbacks(self) -> None:
        if self._callbacks_registered:
            return
        self._remote.add_is_on_updated_callback(self._on_is_on)
        self._remote.add_current_app_updated_callback(self._on_current_app)
        self._remote.add_volume_info_updated_callback(self._on_volume)
        self._remote.add_is_available_updated_callback(self._on_available)
        self._callbacks_registered = True

    def _remove_callbacks(self) -> None:
        if not self._callbacks_registered:
            return
        for method_name, callback in (
            ("remove_is_on_updated_callback", self._on_is_on),
            ("remove_current_app_updated_callback", self._on_current_app),
            ("remove_volume_info_updated_callback", self._on_volume),
            ("remove_is_available_updated_callback", self._on_available),
        ):
            remove = getattr(self._remote, method_name, None)
            if callable(remove):
                try:
                    remove(callback)
                except ValueError:
                    pass
        self._callbacks_registered = False

    def _device_from_remote(self, name: Any, mac_address: Any) -> RemoteV2Device:
        normalized_mac = _normalized_mac(str(mac_address))
        info = self._remote.device_info or {}
        opaque_identity = hashlib.sha256(normalized_mac.encode("ascii")).hexdigest()[:24]
        return RemoteV2Device(
            identity=f"android-tv-v2:{opaque_identity}",
            name=_optional_text(name) or "Android TV",
            manufacturer=_optional_text(info.get("manufacturer")),
            model=_optional_text(info.get("model")),
            software_version=_optional_text(info.get("sw_version")),
        )

    def _update_device_info(self) -> None:
        if self._device is None:
            return
        info = self._remote.device_info or {}
        self._device = RemoteV2Device(
            identity=self._device.identity,
            name=self._device.name,
            manufacturer=_optional_text(info.get("manufacturer")),
            model=_optional_text(info.get("model")),
            software_version=_optional_text(info.get("sw_version")),
        )

    def _on_is_on(self, value: bool) -> None:
        self._is_on = value
        self._emit_snapshot()

    def _on_current_app(self, value: str) -> None:
        self._current_app = _optional_text(value)
        self._emit_snapshot()

    def _on_volume(self, value: Any) -> None:
        self._volume = self._volume_from_remote(value)
        self._emit_snapshot()

    def _on_available(self, value: bool) -> None:
        self._available = value
        self._emit_snapshot()

    def _on_reauth_required(self) -> None:
        self._available = False
        self._authenticated = False
        self._reauth_required = True
        self._emit_snapshot()

    @staticmethod
    def _volume_from_remote(value: Any) -> RemoteV2Volume | None:
        if not value:
            return None
        return RemoteV2Volume(
            level=int(value["level"]),
            maximum=int(value["max"]),
            muted=bool(value["muted"]),
        )

    def _emit_snapshot(self) -> RemoteV2Snapshot:
        snapshot = self.snapshot
        for callback in tuple(self._callbacks):
            try:
                callback(snapshot)
            except Exception:
                _LOGGER.exception("Android TV snapshot callback failed")
        return snapshot
