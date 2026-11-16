from __future__ import annotations

import pytest

from piphi_network_reolink import state
from piphi_network_reolink.schemas import DeviceConfig


class FakeClient:
    def __init__(self, *, hardware_id: str = "device-hash") -> None:
        self.closed = False
        self.hardware_id = hardware_id
        self.fail = False

    async def refresh(self):
        if self.fail:
            raise ConnectionError("camera-secret")
        return {
            "connected": True,
            "camera_count": 1,
            "name": "Front door",
            "model": "D340W",
            "hardware": "DB_566128M5MP_W",
            "firmware": "v3.0",
            "hardware_id": self.hardware_id,
            "is_nvr": False,
            "is_battery": False,
            "channels": [
                {
                    "channel": 0,
                    "hardware_id": "channel-hash",
                    "name": "Front door",
                    "model": "D340W",
                    "hardware": "DB_566128M5MP_W",
                    "firmware": "v3.0",
                    "online": True,
                    "sleeping": False,
                    "is_doorbell": True,
                    "features": ["snapshot", "stream"],
                }
            ],
        }

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_config_redacts_password_and_refresh_discovers_channels(monkeypatch) -> None:
    client = FakeClient()

    async def connect(**kwargs):
        assert kwargs["password"] == "camera-secret"
        return client

    monkeypatch.setattr(state.runtime_data, "client_connector", connect)
    config = DeviceConfig(
        id="front-door",
        host="192.0.2.20",
        username="piphi",
        password="camera-secret",
    )
    await state.apply_config(config)
    try:
        entry = state.registry.get("front-door")
        assert entry is not None
        assert "password" not in entry["config"]

        snapshot = await state.refresh_entry(entry)

        assert snapshot["camera_count"] == 1
        assert entry["channels"][0]["name"] == "Front door"
        published = state.registry.state_snapshots["front-door"]["state"]
        assert published["connected"] is True
        assert published["camera_count"] == 1
    finally:
        await state.remove_config("front-door")

    assert client.closed is True


@pytest.mark.anyio
async def test_refresh_failure_publishes_offline_without_leaking_error(monkeypatch) -> None:
    client = FakeClient()

    async def connect(**_kwargs):
        return client

    monkeypatch.setattr(state.runtime_data, "client_connector", connect)
    config = DeviceConfig(
        id="offline-camera",
        host="192.0.2.21",
        username="piphi",
        password="camera-secret",
    )
    await state.apply_config(config)
    try:
        entry = state.registry.get("offline-camera")
        assert entry is not None
        client.fail = True
        snapshot = await state.refresh_entry(entry)
        assert snapshot["connected"] is False
        assert snapshot["camera_count"] == 1
        assert len(snapshot["channels"]) == 1
        assert entry["availability"] == "unavailable"
        assert "camera-secret" not in str(state.registry.recent_events)
    finally:
        await state.remove_config("offline-camera")


@pytest.mark.anyio
async def test_failed_reconfigure_keeps_working_client(monkeypatch) -> None:
    working = FakeClient()

    async def connect(**kwargs):
        if kwargs["password"] == "bad-secret":
            raise state.ReolinkSetupError("invalid_auth")
        return working

    monkeypatch.setattr(state.runtime_data, "client_connector", connect)
    original = DeviceConfig(id="front-door", host="192.0.2.20", username="piphi", password="ok")
    await state.apply_config(original)
    try:
        replacement = DeviceConfig(
            id="front-door",
            host="192.0.2.20",
            username="piphi",
            password="bad-secret",
        )
        with pytest.raises(Exception) as raised:
            await state.apply_config(replacement)

        assert getattr(raised.value, "status_code", None) == 422
        assert state.runtime_data.clients["front-door"] is working
        assert working.closed is False
    finally:
        await state.remove_config("front-door")


@pytest.mark.anyio
async def test_duplicate_hardware_is_rejected(monkeypatch) -> None:
    async def connect(**_kwargs):
        return FakeClient(hardware_id="same-device")

    monkeypatch.setattr(state.runtime_data, "client_connector", connect)
    await state.apply_config(DeviceConfig(id="one", host="192.0.2.20", username="u", password="p"))
    try:
        with pytest.raises(Exception) as raised:
            await state.apply_config(DeviceConfig(id="two", host="192.0.2.21", username="u", password="p"))
        assert getattr(raised.value, "status_code", None) == 409
    finally:
        await state.remove_config("one")
