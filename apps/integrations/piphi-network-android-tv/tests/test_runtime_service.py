from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from piphi_network_android_tv.adb_sidecar_client import (
    AdbDeviceSnapshot,
    AdbSidecarError,
)
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


class AdbSessions:
    def __init__(self) -> None:
        self.configured = []
        self.refreshed = []
        self.keys = []
        self.removed = []
        self.error: AdbSidecarError | None = None

    @staticmethod
    def snapshot() -> AdbDeviceSnapshot:
        return AdbDeviceSnapshot(
            connected=True,
            authorized=True,
            manufacturer="Example",
            model="ADB TV",
            android_release="14",
            android_sdk="34",
            queue_depth=0,
            queue_capacity=8,
            reconnect_count=2,
            timeout_count=1,
            last_error_code=None,
        )

    async def configure(self, config):
        self.configured.append(config)
        if self.error:
            raise self.error
        return self.snapshot()

    async def refresh(self, config_id, *, timeout_ms):
        self.refreshed.append((config_id, timeout_ms))
        if self.error:
            raise self.error
        return self.snapshot()

    async def send_key(self, config_id, key, *, timeout_ms):
        self.keys.append((config_id, key, timeout_ms))
        if self.error:
            raise self.error

    async def remove(self, config_id):
        self.removed.append(config_id)
        if self.error:
            raise self.error
        return True

    async def close(self):
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


def test_adb_configure_refresh_key_and_remove_are_explicitly_routed(tmp_path: Path) -> None:
    registry = Registry()
    adb = AdbSessions()
    sessions = Sessions(sample_snapshot())
    service = AndroidTVRuntimeService(
        registry=registry,
        sessions=sessions,
        credentials=lambda _: (tmp_path, tmp_path),
        adb=adb,
    )
    config = DeviceConfig(
        id="adb-tv",
        host="192.0.2.20",
        transport="adb",
        adb_operation_timeout_ms=2_500,
    )
    entry = {
        "config_id": "adb-tv",
        "device_id": "adb-tv",
        "transport": "adb",
        "config": config.model_dump(exclude={"host"}, mode="json"),
    }

    result = asyncio.run(service.configure(config, entry))
    state = asyncio.run(service.refresh("adb-tv"))
    asyncio.run(service.send_key("adb-tv", "HOME"))
    removed = asyncio.run(service.remove("adb-tv"))

    assert isinstance(result, AdbDeviceSnapshot)
    assert sessions.connected == []
    assert adb.refreshed == [("adb-tv", 2_500)]
    assert adb.keys == [("adb-tv", "HOME", 2_500)]
    assert adb.removed == ["adb-tv"]
    assert state["power_on"] is None
    assert state["current_app_id"] is None
    assert state["volume_level_percent"] is None
    assert state["android_api_level"] == "34"
    assert removed is True


def test_transport_change_requires_deconfiguration(tmp_path: Path) -> None:
    registry = Registry()
    registry.set(
        "tv",
        {"config_id": "tv", "device_id": "tv", "transport": "remote_v2"},
    )
    service = AndroidTVRuntimeService(
        registry=registry,
        sessions=Sessions(sample_snapshot()),
        credentials=lambda _: (tmp_path, tmp_path),
        adb=AdbSessions(),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.configure(
                DeviceConfig(id="tv", host="192.0.2.20", transport="adb"),
                {"config_id": "tv", "device_id": "tv", "transport": "adb"},
            )
        )
    assert exc.value.status_code == 409


def test_adb_queue_full_is_normalized_without_retry(tmp_path: Path) -> None:
    registry = Registry()
    registry.set(
        "tv",
        {
            "config_id": "tv",
            "device_id": "tv",
            "transport": "adb",
            "config": {"adb_operation_timeout_ms": 1_000},
        },
    )
    adb = AdbSessions()
    adb.error = AdbSidecarError("queue_full", "private sidecar detail")
    service = AndroidTVRuntimeService(
        registry=registry,
        sessions=Sessions(sample_snapshot()),
        credentials=lambda _: (tmp_path, tmp_path),
        adb=adb,
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.send_key("tv", "HOME"))
    assert exc.value.status_code == 429
    assert exc.value.detail == "ADB target command queue is full"
    assert adb.keys == [("tv", "HOME", 1_000)]

    assert asyncio.run(service.remove("tv")) is True
    assert registry.get("tv") is None
