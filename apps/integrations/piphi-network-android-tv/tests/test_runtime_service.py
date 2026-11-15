from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from piphi_network_android_tv.remote_v2_adapter import (
    RemoteV2Device,
    RemoteV2Snapshot,
    RemoteV2Volume,
)
from piphi_network_android_tv.runtime_service import AndroidTVRuntimeService
from piphi_network_android_tv.schemas import DeviceConfig


class Registry:
    def __init__(self) -> None:
        self.entries = {}
        self.states = {}

    def set(self, config_id, entry):
        self.entries[config_id] = entry

    def get(self, config_id):
        return self.entries.get(config_id)

    def remove(self, config_id):
        return self.entries.pop(config_id, None)

    def update_state(self, config_id, state, *, device_id):
        self.states[config_id] = {"state": state, "device_id": device_id}


class Sessions:
    def __init__(self, result):
        self.result = result
        self.connected = []
        self.keys = []
        self.removed = []

    async def connect(self, **kwargs):
        self.connected.append(kwargs)
        return self.result

    async def refresh(self, config_id):
        return self.result

    async def send_key(self, config_id, key):
        self.keys.append((config_id, key))

    async def remove(self, config_id):
        self.removed.append(config_id)
        return True

    async def close_all(self):
        return None


def sample_snapshot() -> RemoteV2Snapshot:
    return RemoteV2Snapshot(
        available=True,
        authenticated=True,
        reauth_required=False,
        device=RemoteV2Device(
            identity="android-tv-v2:opaque",
            name="Living Room",
            manufacturer="Example",
            model="TV",
            software_version="14",
        ),
        is_on=True,
        current_app="launcher",
        volume=RemoteV2Volume(level=5, maximum=20, muted=False),
    )


def test_configure_connects_before_saving_and_uses_stable_identity(tmp_path: Path) -> None:
    cert = tmp_path / "client.crt"
    key = tmp_path / "client.key"
    cert.write_text("certificate")
    key.write_text("private key")
    registry = Registry()
    sessions = Sessions(sample_snapshot())
    service = AndroidTVRuntimeService(
        registry=registry, sessions=sessions, credentials=lambda _: (cert, key)
    )
    config = DeviceConfig(id="living-room", host="192.0.2.1", alias="TV")
    entry = {"config_id": "living-room", "device_id": "temporary"}

    result = asyncio.run(service.configure(config, entry))

    assert result.available is True
    assert registry.entries["living-room"]["device_id"] == "android-tv-v2:opaque"
    assert registry.states["living-room"]["state"]["volume_level_percent"] == 25
    assert sessions.connected[0]["host"] == "192.0.2.1"


def test_configure_requires_pairing_credentials_before_saving(tmp_path: Path) -> None:
    registry = Registry()
    service = AndroidTVRuntimeService(
        registry=registry,
        sessions=Sessions(sample_snapshot()),
        credentials=lambda _: (tmp_path / "missing.crt", tmp_path / "missing.key"),
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.configure(
                DeviceConfig(id="tv", host="192.0.2.1"),
                {"config_id": "tv", "device_id": "tv"},
            )
        )
    assert exc.value.status_code == 409
    assert registry.entries == {}


def test_refresh_key_and_removal_use_authenticated_session(tmp_path: Path) -> None:
    registry = Registry()
    registry.set("tv", {"config_id": "tv", "device_id": "stable"})
    sessions = Sessions(sample_snapshot())
    service = AndroidTVRuntimeService(
        registry=registry, sessions=sessions, credentials=lambda _: (tmp_path, tmp_path)
    )

    state = asyncio.run(service.refresh("tv"))
    asyncio.run(service.send_key("tv", "HOME"))
    removed = asyncio.run(service.remove("tv"))

    assert state["connected"] is True
    assert sessions.keys == [("tv", "HOME")]
    assert removed is True
    assert registry.get("tv") is None
