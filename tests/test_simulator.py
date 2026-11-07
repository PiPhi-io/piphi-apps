from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from piphi_network_thinqconnect.lib.client import ThinQApiClient
from piphi_network_thinqconnect.lib.normalization import (
    build_command_catalog,
    normalize_device_snapshot,
)
from piphi_network_thinqconnect.lib.simulator import SimulatedThinQClient
from piphi_network_thinqconnect.lib.refrigerator import derive_refrigerator_controls
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
    assert state["metrics"]["fridge_target_temperature"] == 38
    assert state["metrics"]["freezer_target_temperature"] == -3
    assert state["refrigerator"]["compartments"] == [
        {"location": "fridge", "target_temperature": 38, "unit": "°F"},
        {"location": "freezer", "target_temperature": -3, "unit": "°F"},
    ]


def test_refrigerator_profile_preserves_locations_modes_filters_and_unknown_reads() -> None:
    profile = {
        "property": {
            "temperatureInUnits": [
                {"locationName": "FRIDGE", "targetTemperatureF": {"readable": True}},
                {"locationName": "FREEZER", "targetTemperatureF": {"readable": True}},
            ]
        }
    }
    state = normalize_device_snapshot(
        raw_device={"deviceId": "fridge", "deviceType": "DEVICE_REFRIGERATOR"},
        raw_status={
            "doorStatus": [{"locationName": "MAIN", "doorState": "OPEN"}],
            "temperatureInUnits": [
                {"locationName": "FRIDGE", "targetTemperatureF": 37, "unit": "F"},
                {"locationName": "FREEZER", "targetTemperatureF": 0, "unit": "F"},
                {"locationName": "CONVERTIBLE", "targetTemperatureF": 33, "unit": "F"},
            ],
            "powerSave": {"powerSaveEnabled": "ON"},
            "ecoFriendly": {"ecoFriendlyMode": False},
            "sabbath": {"sabbathMode": "OFF"},
            "refrigeration": {
                "rapidFreeze": True,
                "expressMode": "OFF",
                "expressFridge": "ON",
                "freshAirFilter": "AUTO",
                "freshAirFilterRemainPercent": 72,
                "futureReadableFlag": "ALPHA",
            },
            "waterFilterInfo": {
                "waterFilterState": "GOOD",
                "waterFilter1RemainPercent": 81,
                "waterFilter2RemainPercent": 64,
                "usedTime": 12,
                "unit": "month",
            },
            "notification": {"eventType": "time_to_change_water_filter"},
        },
        raw_profile=profile,
        raw_available_controls=[],
    )

    assert state["metrics"] | {
        "door": "OPEN",
        "door_open": True,
        "fridge_target_temperature": 37,
        "freezer_target_temperature": 0,
        "convertible_target_temperature": 33,
        "power_save_enabled": True,
        "eco_friendly_enabled": False,
        "sabbath_mode_enabled": False,
        "rapid_freeze_enabled": True,
        "express_mode_enabled": False,
        "express_fridge_enabled": True,
        "fresh_air_filter_mode": "AUTO",
        "fresh_air_filter_life": 72,
        "water_filter_state": "GOOD",
        "water_filter_1_life": 81,
        "water_filter_2_life": 64,
        "filter_life": 64,
        "notification": "time_to_change_water_filter",
    } == state["metrics"]
    assert state["device_profile"]["fingerprint"].startswith("sha256:")
    assert state["refrigerator"]["notification"] == {
        "code": "time_to_change_water_filter",
        "known": True,
        "severity": "info",
    }
    assert {
        item["provider_path"]
        for item in state["refrigerator"]["additional_capabilities"]
    } == {"refrigeration.future_readable_flag"}


def test_refrigerator_command_mapping_does_not_alias_distinct_features() -> None:
    commands, command_map = build_command_catalog(
        device_type="DEVICE_REFRIGERATOR",
        capabilities=["target_temperature"],
        available_controls=[
            {
                "method": "set_express_fridge",
                "parameters": [
                    {"name": "express_fridge", "options": ["ON", "OFF"]}
                ],
            },
            {
                "method": "set_one_touch_filter",
                "parameters": [
                    {"name": "one_touch_filter", "options": ["ON", "OFF"]}
                ],
            },
        ],
    )

    assert command_map["enable_express_fridge"] == {
        "control_method": "set_express_fridge",
        "control_params": {"express_fridge": "ON"},
        "arg_map": {},
    }
    assert command_map["disable_express_fridge"]["control_params"] == {
        "express_fridge": "OFF"
    }
    assert "enable_rapid_freeze" not in command_map
    assert "disable_rapid_freeze" not in command_map
    assert {command["id"] for command in commands} >= {
        "enable_express_fridge",
        "disable_express_fridge",
    }


def test_refrigerator_temperature_command_preserves_required_compartment() -> None:
    commands, command_map = build_command_catalog(
        device_type="DEVICE_REFRIGERATOR",
        capabilities=["target_temperature"],
        available_controls=[
            {
                "method": "set_target_temperature",
                "parameters": [
                    {
                        "name": "locationName",
                        "type": "string",
                        "options": ["FRIDGE", "FREEZER", "CONVERTIBLE"],
                    },
                    {
                        "name": "targetTemperatureF",
                        "type": "number",
                        "min": -6,
                        "max": 43,
                        "unit": "°F",
                    },
                ],
            }
        ],
    )

    assert command_map["set_target_temperature"]["arg_map"] == {
        "temperature": "targetTemperatureF",
        "location": "locationName",
    }
    command = next(item for item in commands if item["id"] == "set_target_temperature")
    assert command["args_schema"]["location"] == {
        "type": "string",
        "label": "Compartment",
        "required": True,
        "options": ["FRIDGE", "FREEZER", "CONVERTIBLE"],
    }


def test_refrigerator_controls_are_derived_only_from_writable_profile_properties() -> None:
    controls = derive_refrigerator_controls(
        {
            "property": {
                "refrigeration": {
                    "rapidFreeze": {
                        "type": "boolean",
                        "mode": ["r"],
                    },
                    "expressFridge": {
                        "type": "boolean",
                        "mode": ["r", "w"],
                        "value": {"w": [True, False]},
                    },
                }
            }
        }
    )

    assert controls == [
        {
            "method": "set_express_fridge",
            "resource": "refrigeration",
            "parameters": [
                {
                    "name": "expressFridge",
                    "type": "boolean",
                    "required": True,
                    "options": [True, False],
                }
            ],
        }
    ]
    _commands, command_map = build_command_catalog(
        device_type="DEVICE_REFRIGERATOR",
        capabilities=[],
        available_controls=controls,
    )
    assert command_map["enable_express_fridge"] == {
        "control_method": "set_express_fridge",
        "control_params": {"expressFridge": True},
        "arg_map": {},
        "control_resource": "refrigeration",
    }


def test_live_client_posts_profile_shaped_control_payload(monkeypatch) -> None:
    captured: list[tuple[str, dict]] = []

    class FakeApi:
        async def async_post_device_control(self, device_id, payload):
            captured.append((device_id, payload))
            return {"status": "accepted"}

    @asynccontextmanager
    async def fake_api(**_kwargs):
        yield FakeApi()

    client = ThinQApiClient()
    monkeypatch.setattr(client, "_api", fake_api)
    result = asyncio.run(
        client.execute_device_command(
            access_token="secret",
            country_code="US",
            device_id="fridge-1",
            device_type="DEVICE_REFRIGERATOR",
            control_method="set_express_fridge",
            control_params={"expressFridge": True},
            control_resource="refrigeration",
        )
    )

    assert result == {"status": "accepted"}
    assert captured == [
        ("fridge-1", {"refrigeration": {"expressFridge": True}})
    ]


def test_live_client_fetches_profile_with_sdk_device_id_signature(monkeypatch) -> None:
    calls: list[tuple[str, tuple]] = []

    class FakeApi:
        async def async_get_device_list(self):
            return [{"deviceId": "fridge-1", "deviceType": "DEVICE_REFRIGERATOR"}]

        async def async_get_device_status(self, device_id):
            calls.append(("status", (device_id,)))
            return {"online": True}

        async def async_get_device_profile(self, device_id):
            calls.append(("profile", (device_id,)))
            return {"property": {}}

    @asynccontextmanager
    async def fake_api(**_kwargs):
        yield FakeApi()

    client = ThinQApiClient()
    monkeypatch.setattr(client, "_api", fake_api)
    snapshot = asyncio.run(
        client.fetch_device_snapshot(
            access_token="secret",
            country_code="US",
            device_id="fridge-1",
            device_type="DEVICE_REFRIGERATOR",
        )
    )

    assert calls == [
        ("status", ("fridge-1",)),
        ("profile", ("fridge-1",)),
    ]
    assert snapshot["profile"] == {"property": {}}


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
