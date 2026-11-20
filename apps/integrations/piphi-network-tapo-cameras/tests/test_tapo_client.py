from __future__ import annotations

import pytest
from kasa import DeviceType, Discover, Module

from piphi_network_tapo_cameras.tapo_client import TapoClient, TapoSetupError


class LensMask:
    enabled = True


class Device:
    def __init__(self) -> None:
        self.device_type = DeviceType.Camera
        self.children = []
        self.modules = {Module.LensMask: LensMask()}
        self.device_id = "raw-device-id"
        self.alias = "Front"
        self.model = "C100"
        self.hw_info = {"hw_ver": "1.0", "sw_ver": "2.0"}
        self.rssi = -60


def test_snapshot_is_sanitized_and_read_only() -> None:
    snapshot = TapoClient(Device()).snapshot().as_dict()
    assert snapshot["privacy_mode"] is True
    assert snapshot["hardware_id"] != "raw-device-id"
    assert "raw-device-id" not in str(snapshot)


@pytest.mark.parametrize("device_type", [DeviceType.Plug, DeviceType.Hub, DeviceType.Sensor])
def test_non_camera_devices_are_rejected(device_type) -> None:
    device = Device()
    device.device_type = device_type
    with pytest.raises(TapoSetupError, match="unsupported_device"):
        TapoClient(device).snapshot()


def test_battery_devices_are_rejected() -> None:
    device = Device()
    device.modules = {Module.BatterySensor: object()}
    with pytest.raises(TapoSetupError, match="battery_device_unsupported"):
        TapoClient(device).snapshot()


def test_unreadable_privacy_state_is_unknown_not_false() -> None:
    class UnreadableLensMask:
        @property
        def enabled(self):
            raise RuntimeError("raw-provider-canary")

    device = Device()
    device.modules = {Module.LensMask: UnreadableLensMask()}
    assert TapoClient(device).snapshot().privacy_mode is None


@pytest.mark.anyio
async def test_connect_maps_authentication_failure_without_fallback(monkeypatch) -> None:
    class AuthenticationError(Exception):
        pass

    async def fail_discovery(*args, **kwargs):
        raise AuthenticationError("credential-canary")

    fallback_called = False

    async def fallback(*args, **kwargs):
        nonlocal fallback_called
        fallback_called = True

    monkeypatch.setattr(Discover, "discover_single", fail_discovery)
    monkeypatch.setattr(Discover, "try_connect_all", fallback)

    with pytest.raises(TapoSetupError, match="invalid_auth"):
        await TapoClient.connect(host="192.0.2.10", username="user", password="secret")
    assert fallback_called is False


@pytest.mark.anyio
async def test_connect_falls_back_when_targeted_discovery_times_out(monkeypatch) -> None:
    device = Device()

    async def timeout(*args, **kwargs):
        raise TimeoutError

    async def fallback(*args, **kwargs):
        return device

    monkeypatch.setattr(Discover, "discover_single", timeout)
    monkeypatch.setattr(Discover, "try_connect_all", fallback)

    client = await TapoClient.connect(
        host="192.0.2.10", username="user", password="secret"
    )
    assert client.snapshot().model == "C100"
