from __future__ import annotations

from typing import ClassVar

import pytest

from piphi_network_reolink.reolink_client import ReolinkClient


class FakeHost:
    channels: ClassVar[list[int]] = [0, 2]
    nvr_name = "Driveway NVR"
    model = "RLN8-410"
    is_nvr = True
    is_battery = False
    mac_address = "AA:BB:CC:DD:EE:FF"
    uid = "host-uid"
    hardware_version = "N7MB01"
    sw_version = "v3.5.1"
    capabilities: ClassVar[dict] = {
        0: {None: {"stream", "snapshot", "ptz", "firmware"}},
        2: {None: {"stream", "battery", "arbitrary_private_feature"}},
    }

    def __init__(self) -> None:
        self.refreshed = False
        self.closed = False

    async def get_states(self) -> None:
        self.refreshed = True

    async def logout(self) -> None:
        self.closed = True

    def camera_name(self, channel: int) -> str:
        return {0: "Driveway", 2: "Back gate"}[channel]

    def camera_model(self, channel: int) -> str:
        return {0: "RLC-823A", 2: "Argus 4 Pro"}[channel]

    def camera_sw_version(self, channel: int) -> str:
        return f"v3.{channel}"

    def camera_uid(self, channel: int) -> str:
        return f"camera-{channel}"

    def camera_hardware_version(self, channel: int) -> str:
        return "IPC_529SD78MP"

    def sleeping(self, channel: int) -> bool:
        return False

    def camera_online(self, channel: int) -> bool:
        return channel == 0

    def is_doorbell(self, channel: int) -> bool:
        return False


@pytest.mark.anyio
async def test_refresh_normalizes_nvr_channels_and_filters_features() -> None:
    host = FakeHost()
    client = ReolinkClient(host)

    snapshot = await client.refresh()

    assert host.refreshed is True
    assert snapshot["connected"] is True
    assert snapshot["camera_count"] == 2
    assert snapshot["is_nvr"] is True
    assert snapshot["hardware_id"] is not None
    assert snapshot["hardware_id"] != FakeHost.mac_address
    assert snapshot["channels"][0] == {
        "channel": 0,
        "hardware_id": snapshot["channels"][0]["hardware_id"],
        "name": "Driveway",
        "model": "RLC-823A",
        "hardware": "IPC_529SD78MP",
        "firmware": "v3.0",
        "online": True,
        "sleeping": False,
        "is_doorbell": False,
        "features": ["ptz", "snapshot", "stream"],
    }
    assert snapshot["channels"][1]["features"] == ["battery", "stream"]


@pytest.mark.anyio
async def test_close_logs_out() -> None:
    host = FakeHost()
    await ReolinkClient(host).close()
    assert host.closed is True
