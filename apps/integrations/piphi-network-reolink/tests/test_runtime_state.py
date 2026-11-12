from __future__ import annotations

import pytest

from piphi_network_reolink import state
from piphi_network_reolink.schemas import DeviceConfig


class FakeClient:
    def __init__(self) -> None:
        self.closed = False

    async def refresh(self):
        return {
            "connected": True,
            "camera_count": 1,
            "name": "Front door",
            "model": "D340W",
            "is_nvr": False,
            "channels": [
                {
                    "channel": 0,
                    "name": "Front door",
                    "model": "D340W",
                    "firmware": "v3.0",
                    "online": True,
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

    monkeypatch.setattr(state, "_client_connector", connect)
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
    async def connect(**_kwargs):
        raise ConnectionError("camera-secret")

    monkeypatch.setattr(state, "_client_connector", connect)
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
        snapshot = await state.refresh_entry(entry)
        assert snapshot == {"connected": False, "camera_count": 0, "channels": []}
        assert "camera-secret" not in str(state.registry.recent_events)
    finally:
        await state.remove_config("offline-camera")
