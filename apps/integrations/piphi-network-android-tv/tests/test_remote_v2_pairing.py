from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest

from piphi_network_android_tv.remote_v2_pairing import (
    InvalidConfigIdError,
    PairingAlreadyActiveError,
    PairingSessionNotFoundError,
    RemoteV2CredentialStore,
    RemoteV2PairingManager,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class FakeAdapter:
    def __init__(self, *, certfile: str, keyfile: str, **kwargs: Any) -> None:
        self.certfile = Path(certfile)
        self.keyfile = Path(keyfile)
        self.kwargs = kwargs
        self.finished_pins: list[str] = []
        self.disconnect_count = 0
        self.fail_start = False
        self.fail_finish = False

    async def start_pairing(self) -> tuple[str, str]:
        self.certfile.write_text("certificate-secret")
        self.keyfile.write_text("private-key-secret")
        if self.fail_start:
            raise RuntimeError("pairing start failed")
        return "Living Room", "AA:BB:CC:DD:EE:FF"

    async def finish_pairing(self, pin: str) -> None:
        self.finished_pins.append(pin)
        if self.fail_finish:
            raise RuntimeError("pairing finish failed")

    async def disconnect(self) -> None:
        self.disconnect_count += 1


class FakeFactory:
    def __init__(self) -> None:
        self.adapters: list[FakeAdapter] = []
        self.fail_next_start = False
        self.fail_next_finish = False

    def __call__(self, **kwargs: Any) -> FakeAdapter:
        adapter = FakeAdapter(**kwargs)
        adapter.fail_start = self.fail_next_start
        adapter.fail_finish = self.fail_next_finish
        self.fail_next_start = False
        self.fail_next_finish = False
        self.adapters.append(adapter)
        return adapter


def make_manager(tmp_path: Path, *, ttl: float = 60.0):
    clock = FakeClock()
    factory = FakeFactory()
    store = RemoteV2CredentialStore(tmp_path / "credentials")
    manager = RemoteV2PairingManager(
        store, adapter_factory=factory, clock=clock, pairing_ttl_seconds=ttl
    )
    return manager, store, factory, clock


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def test_credential_paths_are_confined_and_restrictive(tmp_path: Path) -> None:
    store = RemoteV2CredentialStore(tmp_path / "credentials")
    paths = store.paths_for("living-room_1", create=True)
    paths.certfile.write_text("cert")
    paths.keyfile.write_text("key")
    os.chmod(paths.certfile, 0o666)
    os.chmod(paths.keyfile, 0o644)

    store.paths_for("living-room_1")

    assert mode(store.root) == 0o700
    assert mode(paths.directory) == 0o700
    assert mode(paths.certfile) == 0o600
    assert mode(paths.keyfile) == 0o600
    assert store.has_credentials("living-room_1") is True

    for unsafe in ("../escape", "/absolute", "two/parts", ".", "..", "space id", ""):
        with pytest.raises(InvalidConfigIdError):
            store.paths_for(unsafe, create=True)


def test_credential_store_rejects_symlink_files(tmp_path: Path) -> None:
    store = RemoteV2CredentialStore(tmp_path / "credentials")
    paths = store.paths_for("tv", create=True)
    target = tmp_path / "outside"
    target.write_text("do not touch")
    paths.keyfile.symlink_to(target)

    with pytest.raises(OSError, match="not a regular file"):
        store.paths_for("tv")
    assert target.read_text() == "do not touch"


def test_start_and_finish_are_one_shot_and_do_not_persist_pin(tmp_path: Path) -> None:
    manager, store, factory, clock = make_manager(tmp_path)

    session = asyncio.run(manager.start_pairing(config_id="tv-1", host="192.0.2.4"))
    paths = store.paths_for("tv-1")

    assert len(session.session_id) >= 40
    assert session.expires_at == clock.now + 60
    assert session.device_name == "Living Room"
    assert not hasattr(session, "mac_address")
    assert "certificate-secret" not in repr(session)
    assert mode(paths.certfile) == mode(paths.keyfile) == 0o600

    asyncio.run(manager.finish_pairing(session.session_id, "a1b2c3"))

    assert factory.adapters[0].finished_pins == ["a1b2c3"]
    assert factory.adapters[0].disconnect_count == 1
    assert store.has_credentials("tv-1") is True
    assert not hasattr(manager, "pin")
    with pytest.raises(PairingSessionNotFoundError):
        asyncio.run(manager.finish_pairing(session.session_id, "ffffff"))


def test_active_session_is_unique_per_config_and_can_be_cancelled(tmp_path: Path) -> None:
    manager, store, factory, _clock = make_manager(tmp_path)
    session = asyncio.run(manager.start_pairing(config_id="tv", host="192.0.2.4"))

    with pytest.raises(PairingAlreadyActiveError):
        asyncio.run(manager.start_pairing(config_id="tv", host="192.0.2.4"))

    asyncio.run(manager.cancel_pairing(session.session_id))

    assert factory.adapters[0].disconnect_count == 1
    assert store.has_credentials("tv") is False
    with pytest.raises(PairingSessionNotFoundError):
        asyncio.run(manager.cancel_pairing(session.session_id))


def test_cleanup_expires_sessions_and_removes_unpaired_credentials(tmp_path: Path) -> None:
    manager, store, factory, clock = make_manager(tmp_path, ttl=10)
    session = asyncio.run(manager.start_pairing(config_id="tv", host="192.0.2.4"))
    clock.now = session.expires_at

    assert asyncio.run(manager.cleanup()) == 1
    assert factory.adapters[0].disconnect_count == 1
    assert store.has_credentials("tv") is False
    with pytest.raises(PairingSessionNotFoundError):
        asyncio.run(manager.finish_pairing(session.session_id, "abcdef"))


def test_start_and_finish_failures_clean_up_session_and_new_files(tmp_path: Path) -> None:
    manager, store, factory, _clock = make_manager(tmp_path)
    factory.fail_next_start = True
    with pytest.raises(RuntimeError, match="start failed"):
        asyncio.run(manager.start_pairing(config_id="start-fail", host="192.0.2.4"))
    assert factory.adapters[0].disconnect_count == 1
    assert store.has_credentials("start-fail") is False

    factory.fail_next_finish = True
    session = asyncio.run(manager.start_pairing(config_id="finish-fail", host="192.0.2.4"))
    with pytest.raises(RuntimeError, match="finish failed"):
        asyncio.run(manager.finish_pairing(session.session_id, "abcdef"))
    assert factory.adapters[1].disconnect_count == 1
    assert store.has_credentials("finish-fail") is False
    with pytest.raises(PairingSessionNotFoundError):
        asyncio.run(manager.finish_pairing(session.session_id, "abcdef"))


def test_existing_credentials_survive_failed_repairing(tmp_path: Path) -> None:
    manager, store, factory, _clock = make_manager(tmp_path)
    paths = store.paths_for("tv", create=True)
    paths.certfile.write_text("old-cert")
    paths.keyfile.write_text("old-key")
    factory.fail_next_finish = True
    session = asyncio.run(manager.start_pairing(config_id="tv", host="192.0.2.4"))

    with pytest.raises(RuntimeError):
        asyncio.run(manager.finish_pairing(session.session_id, "abcdef"))

    assert paths.certfile.exists()
    assert paths.keyfile.exists()


def test_ttl_is_bounded_and_close_discards_all_sessions(tmp_path: Path) -> None:
    store = RemoteV2CredentialStore(tmp_path / "credentials")
    for ttl in (0, -1, 301):
        with pytest.raises(ValueError, match="at most 300"):
            RemoteV2PairingManager(store, pairing_ttl_seconds=ttl)

    manager, store, factory, _clock = make_manager(tmp_path)
    asyncio.run(manager.start_pairing(config_id="one", host="192.0.2.1"))
    asyncio.run(manager.start_pairing(config_id="two", host="192.0.2.2"))
    asyncio.run(manager.close())

    assert [adapter.disconnect_count for adapter in factory.adapters] == [1, 1]
    assert store.has_credentials("one") is False
    assert store.has_credentials("two") is False
