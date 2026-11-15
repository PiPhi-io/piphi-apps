from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .remote_v2_adapter import AndroidTVRemoteV2Adapter, RemoteV2Client

_CONFIG_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
_LOGGER = logging.getLogger(__name__)
_DEFAULT_PAIRING_TTL_SECONDS = 120.0
_MAX_PAIRING_TTL_SECONDS = 300.0

AdapterFactory = Callable[..., RemoteV2Client]
Clock = Callable[[], float]


class InvalidConfigIdError(ValueError):
    """Raised when a config ID cannot safely be used as a directory name."""


class PairingSessionError(RuntimeError):
    """Base class for pairing-session errors."""


class PairingSessionNotFoundError(PairingSessionError):
    """Raised for an unknown, expired, cancelled, or already-used session."""


class PairingAlreadyActiveError(PairingSessionError):
    """Raised when a config already has an active pairing attempt."""


@dataclass(frozen=True, slots=True)
class RemoteV2CredentialPaths:
    directory: Path
    certfile: Path
    keyfile: Path


@dataclass(frozen=True, slots=True)
class PairingSession:
    """Credential-free metadata safe to return to an API caller."""

    session_id: str
    config_id: str
    device_name: str
    expires_at: float


@dataclass(slots=True)
class _ActivePairing:
    public: PairingSession
    adapter: RemoteV2Client
    paths: RemoteV2CredentialPaths
    cert_existed: bool
    key_existed: bool


class RemoteV2CredentialStore:
    """Owns per-config Remote v2 certificate paths and their permissions."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        # Do not resolve here: resolving would silently accept a symlink as the root.
        self._root = Path(root).expanduser().absolute()

    @property
    def root(self) -> Path:
        return self._root

    def paths_for(self, config_id: str, *, create: bool = False) -> RemoteV2CredentialPaths:
        self._validate_config_id(config_id)
        self._ensure_directory(self._root, create=create)
        directory = self._root / config_id
        self._ensure_directory(directory, create=create)
        paths = RemoteV2CredentialPaths(
            directory=directory,
            certfile=directory / "client.crt",
            keyfile=directory / "client.key",
        )
        self.secure_existing_files(paths)
        return paths

    def has_credentials(self, config_id: str) -> bool:
        try:
            paths = self.paths_for(config_id)
        except FileNotFoundError:
            return False
        return self._is_regular_file(paths.certfile) and self._is_regular_file(paths.keyfile)

    def secure_existing_files(self, paths: RemoteV2CredentialPaths) -> None:
        for path in (paths.certfile, paths.keyfile):
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(mode):
                raise OSError(f"credential path is not a regular file: {path.name}")
            path.chmod(0o600)

    def remove_credentials(self, config_id: str) -> None:
        paths = self.paths_for(config_id)
        for path in (paths.certfile, paths.keyfile):
            try:
                mode = path.lstat().st_mode
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(mode):
                raise OSError(f"credential path is not a regular file: {path.name}")
            path.unlink()
        try:
            paths.directory.rmdir()
        except OSError:
            pass

    @staticmethod
    def _validate_config_id(config_id: str) -> None:
        if not isinstance(config_id, str) or not _CONFIG_ID.fullmatch(config_id):
            raise InvalidConfigIdError(
                "config_id must be 1-128 ASCII letters, digits, dots, underscores, or hyphens"
            )
        if config_id in {".", ".."}:
            raise InvalidConfigIdError("config_id cannot be a relative path segment")

    @staticmethod
    def _ensure_directory(path: Path, *, create: bool) -> None:
        if create:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            raise OSError(f"credential directory is not a real directory: {path}")
        path.chmod(0o700)

    @staticmethod
    def _is_regular_file(path: Path) -> bool:
        try:
            return stat.S_ISREG(path.lstat().st_mode)
        except FileNotFoundError:
            return False


class RemoteV2PairingManager:
    """Keeps short-lived Remote v2 pairing state exclusively in memory."""

    def __init__(
        self,
        credential_store: RemoteV2CredentialStore,
        *,
        adapter_factory: AdapterFactory = AndroidTVRemoteV2Adapter,
        clock: Clock = time.monotonic,
        pairing_ttl_seconds: float = _DEFAULT_PAIRING_TTL_SECONDS,
    ) -> None:
        if not 0 < pairing_ttl_seconds <= _MAX_PAIRING_TTL_SECONDS:
            raise ValueError(
                f"pairing_ttl_seconds must be greater than zero and at most {_MAX_PAIRING_TTL_SECONDS:g}"
            )
        self._credentials = credential_store
        self._adapter_factory = adapter_factory
        self._clock = clock
        self._pairing_ttl_seconds = float(pairing_ttl_seconds)
        self._sessions: dict[str, _ActivePairing] = {}
        self._config_sessions: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def adapter_for(self, *, config_id: str, host: str, **kwargs: Any) -> RemoteV2Client:
        """Build an adapter with credential paths, never credential contents."""
        paths = self._credentials.paths_for(config_id, create=True)
        return self._adapter_factory(
            host=host,
            certfile=str(paths.certfile),
            keyfile=str(paths.keyfile),
            **kwargs,
        )

    async def start_pairing(self, *, config_id: str, host: str) -> PairingSession:
        async with self._lock:
            await self._cleanup_expired_locked()
            if config_id in self._config_sessions:
                raise PairingAlreadyActiveError("pairing is already active for this config")

            paths = self._credentials.paths_for(config_id, create=True)
            cert_existed = paths.certfile.exists()
            key_existed = paths.keyfile.exists()
            adapter: RemoteV2Client | None = None
            try:
                adapter = self.adapter_for(config_id=config_id, host=host)
                device_name, _mac_address = await adapter.start_pairing()
                self._credentials.secure_existing_files(paths)
                session_id = secrets.token_urlsafe(32)
                public = PairingSession(
                    session_id=session_id,
                    config_id=config_id,
                    device_name=device_name,
                    expires_at=self._clock() + self._pairing_ttl_seconds,
                )
                self._sessions[session_id] = _ActivePairing(
                    public=public,
                    adapter=adapter,
                    paths=paths,
                    cert_existed=cert_existed,
                    key_existed=key_existed,
                )
                self._config_sessions[config_id] = session_id
                return public
            except BaseException:
                if adapter is not None:
                    await self._disconnect_safely(adapter)
                self._remove_new_credentials(paths, cert_existed, key_existed)
                raise

    async def finish_pairing(self, session_id: str, pin: str) -> None:
        # Consume before awaiting or validating. The PIN is never put on an object.
        async with self._lock:
            await self._cleanup_expired_locked()
            active = self._pop_session(session_id)

        succeeded = False
        try:
            await active.adapter.finish_pairing(pin)
            self._credentials.secure_existing_files(active.paths)
            succeeded = True
        finally:
            await self._disconnect_safely(active.adapter)
            if not succeeded:
                self._remove_new_credentials(
                    active.paths, active.cert_existed, active.key_existed
                )

    async def cancel_pairing(self, session_id: str) -> None:
        async with self._lock:
            await self._cleanup_expired_locked()
            active = self._pop_session(session_id)
        await self._discard(active)

    async def cleanup(self) -> int:
        """Discard expired sessions and return the number removed."""
        async with self._lock:
            return await self._cleanup_expired_locked()

    async def close(self) -> None:
        """Discard every active session during application shutdown."""
        async with self._lock:
            active_sessions = list(self._sessions.values())
            self._sessions.clear()
            self._config_sessions.clear()
        for active in active_sessions:
            await self._discard(active)

    def _pop_session(self, session_id: str) -> _ActivePairing:
        active = self._sessions.pop(session_id, None)
        if active is None:
            raise PairingSessionNotFoundError("pairing session is not active")
        self._config_sessions.pop(active.public.config_id, None)
        return active

    async def _cleanup_expired_locked(self) -> int:
        now = self._clock()
        expired = [
            session_id
            for session_id, active in self._sessions.items()
            if active.public.expires_at <= now
        ]
        active_sessions = [self._pop_session(session_id) for session_id in expired]
        for active in active_sessions:
            await self._discard(active)
        return len(active_sessions)

    async def _discard(self, active: _ActivePairing) -> None:
        await self._disconnect_safely(active.adapter)
        self._remove_new_credentials(active.paths, active.cert_existed, active.key_existed)

    @staticmethod
    async def _disconnect_safely(adapter: RemoteV2Client) -> None:
        try:
            await adapter.disconnect()
        except (OSError, RuntimeError, ValueError):
            # Cleanup must not turn a cancelled/failed pairing into retained state.
            _LOGGER.warning("Failed to disconnect expired pairing session", exc_info=True)

    @staticmethod
    def _remove_new_credentials(
        paths: RemoteV2CredentialPaths, cert_existed: bool, key_existed: bool
    ) -> None:
        for path, existed in (
            (paths.certfile, cert_existed),
            (paths.keyfile, key_existed),
        ):
            if existed:
                continue
            try:
                if stat.S_ISREG(path.lstat().st_mode):
                    path.unlink()
            except FileNotFoundError:
                pass
