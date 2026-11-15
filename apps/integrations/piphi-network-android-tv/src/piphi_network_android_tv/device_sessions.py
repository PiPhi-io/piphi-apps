from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from .remote_v2_adapter import RemoteV2Client, RemoteV2Snapshot

AdapterFactory = Callable[..., RemoteV2Client]
SnapshotSink = Callable[[str, RemoteV2Snapshot], None]


class DuplicateDeviceError(ValueError):
    """Raised when two configurations resolve to the same television."""


class UnknownSessionError(KeyError):
    """Raised when a command targets an unconfigured television."""


@dataclass(slots=True)
class _Session:
    adapter: RemoteV2Client
    remove_callback: Callable[[], None]
    identity: str
    command_lock: asyncio.Lock


class DeviceSessionManager:
    """Own authenticated Remote v2 clients and serialize lifecycle changes."""

    def __init__(self, adapter_factory: AdapterFactory, snapshot_sink: SnapshotSink) -> None:
        self._adapter_factory = adapter_factory
        self._snapshot_sink = snapshot_sink
        self._sessions: dict[str, _Session] = {}
        self._identity_owners: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        *,
        config_id: str,
        host: str,
        certfile: str,
        keyfile: str,
    ) -> RemoteV2Snapshot:
        adapter = self._adapter_factory(host=host, certfile=certfile, keyfile=keyfile)
        remove_callback = adapter.add_snapshot_callback(
            lambda snapshot: self._snapshot_sink(config_id, snapshot)
        )
        try:
            snapshot = await adapter.connect()
            if snapshot.device is None or not snapshot.authenticated:
                raise RuntimeError("Remote v2 did not return authenticated device identity")
            identity = snapshot.device.identity
            async with self._lock:
                owner = self._identity_owners.get(identity)
                if owner is not None and owner != config_id:
                    raise DuplicateDeviceError(
                        f"Android TV is already configured as {owner}"
                    )
                old = self._sessions.pop(config_id, None)
                if old is not None:
                    self._identity_owners.pop(old.identity, None)
                self._sessions[config_id] = _Session(
                    adapter=adapter,
                    remove_callback=remove_callback,
                    identity=identity,
                    command_lock=asyncio.Lock(),
                )
                self._identity_owners[identity] = config_id
            if old is not None:
                old.remove_callback()
                async with old.command_lock:
                    await old.adapter.disconnect()
            return snapshot
        except BaseException:
            remove_callback()
            await adapter.disconnect()
            raise

    async def refresh(self, config_id: str) -> RemoteV2Snapshot:
        return await self._get(config_id).adapter.refresh()

    async def send_key(self, config_id: str, key: str) -> None:
        session = self._get(config_id)
        async with session.command_lock:
            await session.adapter.send_key_command(key)

    async def remove(self, config_id: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(config_id, None)
            if session is None:
                return False
            self._identity_owners.pop(session.identity, None)
        session.remove_callback()
        async with session.command_lock:
            await session.adapter.disconnect()
        return True

    async def close_all(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._identity_owners.clear()
        for session in sessions:
            session.remove_callback()
            async with session.command_lock:
                await session.adapter.disconnect()

    def _get(self, config_id: str) -> _Session:
        try:
            return self._sessions[config_id]
        except KeyError as exc:
            raise UnknownSessionError(config_id) from exc
