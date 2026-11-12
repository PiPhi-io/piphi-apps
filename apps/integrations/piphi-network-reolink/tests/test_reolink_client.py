from __future__ import annotations

from typing import ClassVar

import pytest

from piphi_network_reolink.reolink_client import ReolinkClient


class FakeHost:
    channels: ClassVar[list[int]] = [0, 2]
    nvr_name = "Driveway NVR"
    model = "RLN8-410"
    is_nvr = True
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
    assert snapshot["channels"][0] == {
        "channel": 0,
        "name": "Driveway",
        "model": "RLC-823A",
        "firmware": "v3.0",
        "online": True,
        "is_doorbell": False,
        "features": ["ptz", "snapshot", "stream"],
    }
    assert snapshot["channels"][1]["features"] == ["battery", "stream"]


@pytest.mark.anyio
async def test_close_logs_out() -> None:
    host = FakeHost()
    await ReolinkClient(host).close()
    assert host.closed is True
