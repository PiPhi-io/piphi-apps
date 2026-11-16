from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, Protocol

from fastapi import HTTPException

from .adb_sidecar_client import (
    AdbDeviceSnapshot,
    AdbSidecarError,
)
from .remote_v2_adapter import RemoteV2AuthenticationError, RemoteV2Snapshot
from .schemas import DeviceConfig, TransportType

CredentialResolver = Callable[[str], tuple[Path, Path]]


class SessionManager(Protocol):
    async def connect(
        self, *, config_id: str, host: str, certfile: str, keyfile: str
    ) -> RemoteV2Snapshot: ...

    async def refresh(self, config_id: str) -> RemoteV2Snapshot: ...
    async def send_key(self, config_id: str, key: str) -> None: ...
    async def remove(self, config_id: str) -> bool: ...
    async def close_all(self) -> None: ...


class AdbSessionManager(Protocol):
    async def configure(self, config: DeviceConfig) -> AdbDeviceSnapshot: ...
    async def refresh(self, config_id: str, *, timeout_ms: int) -> AdbDeviceSnapshot: ...
    async def send_key(self, config_id: str, key: str, *, timeout_ms: int) -> None: ...
    async def remove(self, config_id: str) -> bool: ...
    async def close(self) -> None: ...


class AndroidTVRuntimeService:
    """Connect-before-save orchestration for authenticated Remote v2 sessions."""

    def __init__(
        self,
        *,
        registry: Any,
        sessions: SessionManager,
        credentials: CredentialResolver,
        adb: AdbSessionManager | None = None,
    ):
        self.registry = registry
        self.sessions = sessions
        self.credentials = credentials
        self.adb = adb

    async def configure(
        self,
        config: DeviceConfig,
        entry: dict[str, Any],
    ) -> RemoteV2Snapshot | AdbDeviceSnapshot:
        config_id = str(entry["config_id"])
        existing = self.registry.get(config_id)
        if existing is not None and existing.get("transport") != config.transport.value:
            raise HTTPException(
                status_code=409,
                detail="Deconfigure the Android TV before changing its transport",
            )
        if config.transport is TransportType.ADB:
            if self.adb is None:
                raise HTTPException(status_code=503, detail="ADB sidecar is unavailable")
            try:
                adb_snapshot = await self.adb.configure(config)
            except AdbSidecarError as exc:
                self._raise_adb_http(exc)
            adb_entry = {**entry, "transport": TransportType.ADB.value}
            self.registry.set(config_id, adb_entry)
            self._write_adb_snapshot(config_id, adb_snapshot)
            return adb_snapshot

        certfile, keyfile = self.credentials(config_id)
        if not certfile.is_file() or not keyfile.is_file():
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "pairing_required",
                    "message": "Pair this Android TV before saving its configuration",
                },
            )
        try:
            snapshot = await self.sessions.connect(
                config_id=config_id,
                host=config.host,
                certfile=str(certfile),
                keyfile=str(keyfile),
            )
        except HTTPException:
            raise
        except RemoteV2AuthenticationError as exc:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "reauth_required",
                    "message": "Android TV must be paired again",
                },
            ) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Android TV connection timed out") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Unable to authenticate Android TV") from exc
        if snapshot.device is None:
            await self.sessions.remove(config_id)
            raise HTTPException(status_code=502, detail="Android TV did not provide stable identity")

        entry = {
            **entry,
            "device_id": snapshot.device.identity,
            "device_name": snapshot.device.name,
            "transport": TransportType.REMOTE_V2.value,
        }
        self.registry.set(config_id, entry)
        self._write_snapshot(config_id, snapshot)
        return snapshot

    async def refresh(self, config_id: str) -> dict[str, Any]:
        entry = self._require_entry(config_id)
        if entry.get("transport") == TransportType.ADB.value:
            if self.adb is None:
                raise HTTPException(status_code=503, detail="ADB sidecar is unavailable")
            try:
                adb_snapshot = await self.adb.refresh(
                    config_id,
                    timeout_ms=self._adb_timeout_ms(entry),
                )
            except AdbSidecarError as exc:
                self.registry.update_state(
                    config_id,
                    {
                        "connected": False,
                        "adb_authorized": False if exc.code == "unauthorized" else None,
                        "sidecar_last_error_code": exc.code,
                    },
                    device_id=str(entry["device_id"]),
                )
                self._raise_adb_http(exc)
            return self._write_adb_snapshot(config_id, adb_snapshot)
        try:
            remote_snapshot = await self.sessions.refresh(config_id)
        except Exception as exc:
            self.registry.update_state(
                config_id,
                {"connected": False},
                device_id=str(entry["device_id"]),
            )
            raise HTTPException(status_code=502, detail="Android TV refresh failed") from exc
        return self._write_snapshot(config_id, remote_snapshot)

    async def send_key(self, config_id: str, key: str) -> None:
        entry = self._require_entry(config_id)
        if entry.get("transport") == TransportType.ADB.value:
            if self.adb is None:
                raise HTTPException(status_code=503, detail="ADB sidecar is unavailable")
            try:
                await self.adb.send_key(
                    config_id,
                    key,
                    timeout_ms=self._adb_timeout_ms(entry),
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except AdbSidecarError as exc:
                self._raise_adb_http(exc)
            return
        try:
            await self.sessions.send_key(config_id, key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Android TV command failed") from exc

    async def remove(self, config_id: str) -> bool:
        entry = self.registry.get(config_id)
        existed = entry is not None
        if entry is not None and entry.get("transport") == TransportType.ADB.value:
            if self.adb is not None:
                try:
                    await self.adb.remove(config_id)
                except AdbSidecarError:
                    # Local deconfiguration must remain possible while the
                    # dependency is unavailable. A later sidecar lifecycle or
                    # configuration pass reconciles stale dependency state.
                    pass
        else:
            await self.sessions.remove(config_id)
        self.registry.remove(config_id)
        return existed

    async def close(self) -> None:
        await self.sessions.close_all()
        if self.adb is not None:
            await self.adb.close()

    def receive_snapshot(self, config_id: str, snapshot: RemoteV2Snapshot) -> None:
        if self.registry.get(config_id) is not None:
            self._write_snapshot(config_id, snapshot)

    def _write_snapshot(self, config_id: str, snapshot: RemoteV2Snapshot) -> dict[str, Any]:
        entry = self._require_entry(config_id)
        volume_percent = None
        if snapshot.volume is not None and snapshot.volume.maximum > 0:
            volume_percent = round(snapshot.volume.level * 100 / snapshot.volume.maximum)
        state = {
            "connected": snapshot.available,
            "authenticated": snapshot.authenticated,
            "reauth_required": snapshot.reauth_required,
            "power_on": snapshot.is_on,
            "current_app_id": snapshot.current_app,
            "volume_level_percent": volume_percent,
            "muted": snapshot.volume.muted if snapshot.volume is not None else None,
            "manufacturer": snapshot.device.manufacturer if snapshot.device else None,
            "model": snapshot.device.model if snapshot.device else None,
            "software_version": snapshot.device.software_version if snapshot.device else None,
            "transport_type": TransportType.REMOTE_V2.value,
            "adb_authorized": None,
            "android_version": None,
            "android_api_level": None,
            "sidecar_queue_depth": None,
            "sidecar_queue_capacity": None,
            "sidecar_reconnect_count": None,
            "sidecar_command_timeout_count": None,
            "sidecar_last_error_code": None,
            "config_id": config_id,
        }
        self.registry.update_state(config_id, state, device_id=str(entry["device_id"]))
        return state

    def _write_adb_snapshot(
        self,
        config_id: str,
        snapshot: AdbDeviceSnapshot,
    ) -> dict[str, Any]:
        entry = self._require_entry(config_id)
        state = {
            "connected": snapshot.connected,
            "authenticated": snapshot.authorized,
            "reauth_required": not snapshot.authorized,
            "power_on": None,
            "current_app_id": None,
            "volume_level_percent": None,
            "muted": None,
            "manufacturer": snapshot.manufacturer,
            "model": snapshot.model,
            "software_version": snapshot.android_release,
            "transport_type": TransportType.ADB.value,
            "adb_authorized": snapshot.authorized,
            "android_version": snapshot.android_release,
            "android_api_level": snapshot.android_sdk,
            "sidecar_queue_depth": snapshot.queue_depth,
            "sidecar_queue_capacity": snapshot.queue_capacity,
            "sidecar_reconnect_count": snapshot.reconnect_count,
            "sidecar_command_timeout_count": snapshot.timeout_count,
            "sidecar_last_error_code": snapshot.last_error_code,
            "config_id": config_id,
        }
        self.registry.update_state(config_id, state, device_id=str(entry["device_id"]))
        return state

    @staticmethod
    def _raise_adb_http(error: AdbSidecarError) -> NoReturn:
        status_code = {
            "authentication_not_configured": 503,
            "unknown_target": 503,
            "unauthorized": 401,
            "timeout": 504,
            "queue_full": 429,
            "unsupported": 400,
            "offline": 502,
        }.get(error.code, 502)
        detail = {
            401: "ADB target authorization is required",
            400: "ADB operation is not supported",
            429: "ADB target command queue is full",
            502: "ADB target or sidecar is unavailable",
            503: "ADB sidecar is not configured",
            504: "ADB target request timed out",
        }[status_code]
        raise HTTPException(status_code=status_code, detail=detail) from error

    @staticmethod
    def _adb_timeout_ms(entry: dict[str, Any]) -> int:
        config = entry.get("config")
        if isinstance(config, dict):
            value = config.get("adb_operation_timeout_ms")
            if isinstance(value, int) and not isinstance(value, bool):
                return max(100, min(value, 30_000))
        return 5_000

    def _require_entry(self, config_id: str) -> dict[str, Any]:
        entry = self.registry.get(config_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Unknown Android TV configuration")
        return entry
