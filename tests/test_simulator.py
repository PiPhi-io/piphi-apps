from __future__ import annotations

import asyncio

from piphi_network_thinqconnect.lib.normalization import normalize_device_snapshot
from piphi_network_thinqconnect.lib.simulator import SimulatedThinQClient
from piphi_network_thinqconnect.lib.schemas import ThinQDeviceConfig
from pydantic import ValidationError
import pytest


def test_simulator_covers_representative_appliance_families() -> None:
    client = SimulatedThinQClient()
    devices = asyncio.run(client.discover_devices())

    assert {device["device_type"] for device in devices} == {
        "DEVICE_AIR_CONDITIONER",
        "DEVICE_REFRIGERATOR",
        "DEVICE_WASHER",
    }


def test_simulator_uses_live_normalization_and_capability_negotiation() -> None:
    client = SimulatedThinQClient()
    snapshot = asyncio.run(client.fetch_device_snapshot(device_id="sim-thinq-fridge"))
    state = normalize_device_snapshot(
        raw_device=snapshot["device"],
        raw_status=snapshot["status"],
        raw_profile=snapshot["profile"],
        raw_available_controls=snapshot["available_controls"],
    )

    assert state["device_class"] == "refrigeration"
    assert {"door", "filter_life", "target_temperature"}.issubset(state["capabilities"])
    assert state["metrics"]["fresh_air_filter_remain_percent"] == 82
    assert "set_target_temperature" in state["command_map"]


def test_simulator_publishes_dashboard_metrics_for_each_appliance_family() -> None:
    client = SimulatedThinQClient()

    washer_snapshot = asyncio.run(
        client.fetch_device_snapshot(device_id="sim-thinq-washer")
    )
    washer = normalize_device_snapshot(
        raw_device=washer_snapshot["device"],
        raw_status=washer_snapshot["status"],
        raw_profile=washer_snapshot["profile"],
        raw_available_controls=washer_snapshot["available_controls"],
    )
    assert washer["metrics"]["appliance_state"] == "RUNNING"
    assert washer["metrics"]["mode"] == "NORMAL"
    assert washer["metrics"]["remaining_minutes"] == 38
    assert washer["metrics"]["cycle_count"] == 128
    assert {"appliance_state", "remaining_minutes", "cycle_count"}.issubset(
        washer["capabilities"]
    )

    fridge_snapshot = asyncio.run(
        client.fetch_device_snapshot(device_id="sim-thinq-fridge")
    )
    fridge = normalize_device_snapshot(
        raw_device=fridge_snapshot["device"],
        raw_status=fridge_snapshot["status"],
        raw_profile=fridge_snapshot["profile"],
        raw_available_controls=fridge_snapshot["available_controls"],
    )
    assert fridge["metrics"]["door"] == "CLOSED"
    assert fridge["metrics"]["target_temperature"] == 3
    assert fridge["metrics"]["filter_life"] == 82


def test_live_refrigerator_payload_publishes_primary_compartment_temperature() -> None:
    state = normalize_device_snapshot(
        raw_device={
            "deviceId": "live-fridge",
            "deviceInfo": {
                "deviceType": "DEVICE_REFRIGERATOR",
                "modelName": "2REF11EIISAS2",
                "alias": "Somerchille",
                "reportable": True,
            },
        },
        raw_status={
            "temperature": [
                {
                    "targetTemperature": 38,
                    "unit": "F",
                    "locationName": "FRIDGE",
                },
                {
                    "targetTemperature": -3,
                    "unit": "F",
                    "locationName": "FREEZER",
                },
            ],
            "temperatureInUnits": [
                {
                    "targetTemperatureF": 38,
                    "locationName": "FRIDGE",
                    "unit": "F",
                },
            ],
        },
        raw_profile=None,
        raw_available_controls=None,
    )

    assert state["device_name"] == "Somerchille"
    assert state["device_type"] == "DEVICE_REFRIGERATOR"
    assert state["device_class"] == "refrigeration"
    assert state["model"] == "2REF11EIISAS2"
    assert "target_temperature" in state["capabilities"]
    assert "temperature" not in state["capabilities"]
    assert state["metrics"]["target_temperature"] == 38
    assert state["units"]["target_temperature"] == "°F"


def test_simulated_commands_are_bounded_to_discovered_devices() -> None:
    client = SimulatedThinQClient()
    result = asyncio.run(
        client.execute_device_command(
            device_id="sim-thinq-washer",
            control_method="pause",
            control_params={},
        )
    )
    assert result == {
        "status": "ok",
        "simulated": True,
        "control_method": "pause",
        "control_params": {},
        "feedback": "Appliance updated",
    }
    snapshot = asyncio.run(client.fetch_device_snapshot(device_id="sim-thinq-washer"))
    assert snapshot["status"]["current_state"] == "PAUSED"


def test_simulated_setting_command_updates_the_next_snapshot() -> None:
    client = SimulatedThinQClient()
    asyncio.run(
        client.execute_device_command(
            device_id="sim-thinq-ac",
            control_method="set_target_temperature",
            control_params={"temperature": 24},
        )
    )

    snapshot = asyncio.run(client.fetch_device_snapshot(device_id="sim-thinq-ac"))
    assert snapshot["status"]["target_temperature_c"] == 24


def test_live_config_requires_token_but_simulator_does_not() -> None:
    common = {
        "id": "cfg-1",
        "device_id": "sim-thinq-washer",
        "device_type": "DEVICE_WASHER",
        "country_code": "US",
    }
    with pytest.raises(ValidationError):
        ThinQDeviceConfig(**common)
    assert ThinQDeviceConfig(**common, simulation_mode=True).simulation_mode is True
