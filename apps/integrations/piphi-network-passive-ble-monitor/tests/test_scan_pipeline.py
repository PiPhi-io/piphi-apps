from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from piphi_network_passive_ble_monitor import scanner, state
from piphi_network_passive_ble_monitor.bthome import BTHOME_UUID
from piphi_network_passive_ble_monitor.scanner import SensorAdvertisement
from piphi_network_passive_ble_monitor.schemas import DeviceConfig


@pytest.mark.anyio
async def test_bleak_boundary_filters_non_bthome_and_malformed_advertisements(monkeypatch) -> None:
    class FakeBleakScanner:
        @staticmethod
        async def discover(*, timeout: float, return_adv: bool):
            assert timeout == 5
            assert return_adv is True
            return {
                "sensor": (
                    SimpleNamespace(address="aa:bb:cc:dd:ee:ff"),
                    SimpleNamespace(service_data={BTHOME_UUID: bytes.fromhex("40016102C409")}, rssi=-60),
                ),
                "other": (
                    SimpleNamespace(address="11:22:33:44:55:66"),
                    SimpleNamespace(service_data={}, rssi=-70),
                ),
                "encrypted": (
                    SimpleNamespace(address="22:33:44:55:66:77"),
                    SimpleNamespace(service_data={BTHOME_UUID: bytes.fromhex("41")}, rssi=-80),
                ),
            }

    monkeypatch.setitem(sys.modules, "bleak", SimpleNamespace(BleakScanner=FakeBleakScanner))
    assert await scanner.scan_bthome() == [
        SensorAdvertisement(
            address="AA:BB:CC:DD:EE:FF",
            metrics={"trigger_based": False, "battery_percent": 97, "temperature_c": 25.0},
            rssi=-60,
        )
    ]


@pytest.mark.anyio
async def test_configured_sensor_is_live_only_after_scan_and_goes_stale(monkeypatch) -> None:
    sent: list[dict] = []
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: sent.append(kwargs))
    config = DeviceConfig(id="ble-test", host="AA:BB:CC:DD:EE:FF", poll_interval_seconds=30)
    await state.apply_config(config)
    try:
        assert state.registry.state_snapshots["ble-test"]["state"]["connected"] is False
        state.process_observations(
            [
                SensorAdvertisement(
                    address="AA:BB:CC:DD:EE:FF",
                    metrics={
                        "trigger_based": False,
                        "temperature_c": 22.5,
                        "humidity_percent": 48.0,
                        "battery_percent": 83,
                    },
                    rssi=-62,
                ),
                SensorAdvertisement(
                    address="11:22:33:44:55:66",
                    metrics={"trigger_based": False, "temperature_c": 99},
                    rssi=-20,
                ),
            ],
            now=100,
        )
        assert sent[-1]["metrics"]["temperature_c"] == 22.5
        assert sent[-1]["metrics"]["humidity_percent"] == 48.0
        assert sent[-1]["metrics"]["battery_percent"] == 83
        assert sent[-1]["metrics"]["rssi_dbm"] == -62
        assert sent[-1]["metrics"]["connected"] is True
        assert sent[-1]["units"] == {
            "battery_percent": "%",
            "temperature_c": "°C",
            "humidity_percent": "%",
            "rssi_dbm": "dBm",
        }
        assert "trigger_based" not in sent[-1]["metrics"]
        state.process_observations([], now=191)
        assert state.registry.state_snapshots["ble-test"]["state"]["connected"] is False
    finally:
        await state.remove_config("ble-test")


@pytest.mark.anyio
async def test_trigger_based_sensor_is_not_marked_offline_between_irregular_packets(monkeypatch) -> None:
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: None)
    await state.apply_config(DeviceConfig(id="trigger-test", host="AA:BB:CC:DD:EE:FF", poll_interval_seconds=30))
    try:
        state.process_observations(
            [SensorAdvertisement("AA:BB:CC:DD:EE:FF", {"trigger_based": True, "battery_percent": 80}, -50)],
            now=100,
        )
        state.process_observations([], now=1000)
        assert state.registry.state_snapshots["trigger-test"]["state"]["connected"] is True
    finally:
        await state.remove_config("trigger-test")


def test_config_requires_ble_address() -> None:
    with pytest.raises(ValueError, match="BLE MAC"):
        DeviceConfig(id="bad", host="127.0.0.1")
