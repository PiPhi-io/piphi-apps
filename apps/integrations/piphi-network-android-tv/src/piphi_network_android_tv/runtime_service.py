from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException

from .remote_v2_adapter import RemoteV2AuthenticationError, RemoteV2Snapshot
from .schemas import DeviceConfig

CredentialResolver = Callable[[str], tuple[Path, Path]]


class SessionManager(Protocol):
    async def connect(
        self, *, config_id: str, host: str, certfile: str, keyfile: str
    ) -> RemoteV2Snapshot: ...

    async def refresh(self, config_id: str) -> RemoteV2Snapshot: ...
    async def send_key(self, config_id: str, key: str) -> None: ...
    async def remove(self, config_id: str) -> bool: ...
    async def close_all(self) -> None: ...


class AndroidTVRuntimeService:
    """Connect-before-save orchestration for authenticated Remote v2 sessions."""

    def __init__(self, *, registry: Any, sessions: SessionManager, credentials: CredentialResolver):
        self.registry = registry
        self.sessions = sessions
        self.credentials = credentials

    async def configure(self, config: DeviceConfig, entry: dict[str, Any]) -> RemoteV2Snapshot:
        config_id = str(entry["config_id"])
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
        }
        self.registry.set(config_id, entry)
        self._write_snapshot(config_id, snapshot)
        return snapshot

    async def refresh(self, config_id: str) -> dict[str, Any]:
        entry = self._require_entry(config_id)
        try:
            snapshot = await self.sessions.refresh(config_id)
        except Exception as exc:
            self.registry.update_state(
                config_id,
                {"connected": False},
                device_id=str(entry["device_id"]),
            )
            raise HTTPException(status_code=502, detail="Android TV refresh failed") from exc
        return self._write_snapshot(config_id, snapshot)

    async def send_key(self, config_id: str, key: str) -> None:
        self._require_entry(config_id)
        try:
            await self.sessions.send_key(config_id, key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Android TV command failed") from exc

    async def remove(self, config_id: str) -> bool:
        existed = self.registry.get(config_id) is not None
        await self.sessions.remove(config_id)
        self.registry.remove(config_id)
        return existed

    async def close(self) -> None:
        await self.sessions.close_all()

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
            "config_id": config_id,
        }
        self.registry.update_state(config_id, state, device_id=str(entry["device_id"]))
        return state

    def _require_entry(self, config_id: str) -> dict[str, Any]:
        entry = self.registry.get(config_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Unknown Android TV configuration")
        return entry
