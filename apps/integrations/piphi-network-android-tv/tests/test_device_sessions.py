from __future__ import annotations

import asyncio

import pytest

from piphi_network_android_tv.device_sessions import (
    DeviceSessionManager,
    DuplicateDeviceError,
    UnknownSessionError,
)
from piphi_network_android_tv.remote_v2_adapter import (
    RemoteV2Device,
    RemoteV2Snapshot,
)


def snapshot(identity: str, *, available: bool = True) -> RemoteV2Snapshot:
    return RemoteV2Snapshot(
        available=available,
        authenticated=True,
        reauth_required=False,
        device=RemoteV2Device(identity=identity, name="TV"),
        is_on=True,
        current_app="launcher",
        volume=None,
    )


class FakeAdapter:
    def __init__(self, result: RemoteV2Snapshot) -> None:
        self.result = result
        self.callback = None
        self.disconnected = 0
        self.removed = 0
        self.keys: list[str] = []

    @property
    def snapshot(self) -> RemoteV2Snapshot:
        return self.result

    def add_snapshot_callback(self, callback):
        self.callback = callback

        def remove() -> None:
            self.removed += 1

        return remove

    async def connect(self) -> RemoteV2Snapshot:
        return self.result

    async def disconnect(self) -> None:
        self.disconnected += 1

    async def refresh(self) -> RemoteV2Snapshot:
        if self.callback:
            self.callback(self.result)
        return self.result

    async def send_key_command(self, key: str) -> None:
        self.keys.append(key)


def test_connect_routes_snapshots_and_commands_to_one_session() -> None:
    adapter = FakeAdapter(snapshot("device-a"))
    observed = []
    manager = DeviceSessionManager(lambda **_: adapter, lambda cid, item: observed.append((cid, item)))

    asyncio.run(manager.connect(config_id="living-room", host="tv", certfile="c", keyfile="k"))
    asyncio.run(manager.refresh("living-room"))
    asyncio.run(manager.send_key("living-room", "HOME"))

    assert observed[-1][0] == "living-room"
    assert adapter.keys == ["HOME"]


def test_duplicate_stable_identity_is_rejected_and_candidate_is_closed() -> None:
    first = FakeAdapter(snapshot("same-device"))
    second = FakeAdapter(snapshot("same-device"))
    adapters = iter((first, second))
    manager = DeviceSessionManager(lambda **_: next(adapters), lambda *_: None)
    asyncio.run(manager.connect(config_id="one", host="one", certfile="c", keyfile="k"))

    with pytest.raises(DuplicateDeviceError):
        asyncio.run(manager.connect(config_id="two", host="two", certfile="c", keyfile="k"))

    assert second.disconnected == 1
    assert second.removed == 1


def test_replacing_and_removing_session_cleans_up_previous_client() -> None:
    first = FakeAdapter(snapshot("device-a"))
    second = FakeAdapter(snapshot("device-b"))
    adapters = iter((first, second))
    manager = DeviceSessionManager(lambda **_: next(adapters), lambda *_: None)
    asyncio.run(manager.connect(config_id="tv", host="old", certfile="c", keyfile="k"))
    asyncio.run(manager.connect(config_id="tv", host="new", certfile="c", keyfile="k"))

    assert first.disconnected == 1
    assert first.removed == 1
    assert asyncio.run(manager.remove("tv")) is True
    assert second.disconnected == 1
    assert asyncio.run(manager.remove("tv")) is False


def test_failed_connect_and_unknown_target_fail_closed() -> None:
    class FailingAdapter(FakeAdapter):
        async def connect(self) -> RemoteV2Snapshot:
            raise TimeoutError

    adapter = FailingAdapter(snapshot("device-a"))
    manager = DeviceSessionManager(lambda **_: adapter, lambda *_: None)
    with pytest.raises(TimeoutError):
        asyncio.run(manager.connect(config_id="tv", host="tv", certfile="c", keyfile="k"))
    assert adapter.disconnected == 1

    with pytest.raises(UnknownSessionError):
        asyncio.run(manager.refresh("missing"))


def test_close_all_disconnects_every_session() -> None:
    first = FakeAdapter(snapshot("device-a"))
    second = FakeAdapter(snapshot("device-b"))
    adapters = iter((first, second))
    manager = DeviceSessionManager(lambda **_: next(adapters), lambda *_: None)
    asyncio.run(manager.connect(config_id="one", host="one", certfile="c", keyfile="k"))
    asyncio.run(manager.connect(config_id="two", host="two", certfile="c", keyfile="k"))

    asyncio.run(manager.close_all())

    assert first.disconnected == second.disconnected == 1


def test_commands_are_serialized_per_device() -> None:
    class BlockingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__(snapshot("device-a"))
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def send_key_command(self, key: str) -> None:
            self.keys.append(key)
            if key == "HOME":
                self.first_started.set()
                await self.release_first.wait()

    async def scenario() -> None:
        adapter = BlockingAdapter()
        manager = DeviceSessionManager(lambda **_: adapter, lambda *_: None)
        await manager.connect(config_id="tv", host="tv", certfile="c", keyfile="k")
        first = asyncio.create_task(manager.send_key("tv", "HOME"))
        await adapter.first_started.wait()
        second = asyncio.create_task(manager.send_key("tv", "BACK"))
        await asyncio.sleep(0)
        assert adapter.keys == ["HOME"]
        adapter.release_first.set()
        await asyncio.gather(first, second)
        assert adapter.keys == ["HOME", "BACK"]

    asyncio.run(scenario())
