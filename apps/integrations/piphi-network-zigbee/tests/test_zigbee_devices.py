from __future__ import annotations

from piphi_network_zigbee.zigbee_devices import (
    available_commands_for,
    normalize_zigbee2mqtt_device,
)


def test_normalizes_zigbee2mqtt_device_capabilities() -> None:
    device = normalize_zigbee2mqtt_device(
        {
            "friendly_name": "kitchen_light",
            "ieee_address": "0x00158d0000000001",
            "definition": {
                "model": "TS0505B",
                "vendor": "Tuya",
                "exposes": [
                    {
                        "type": "light",
                        "features": [
                            {"property": "state"},
                            {"property": "brightness"},
                            {"property": "color_temp"},
                        ],
                    }
                ],
            },
        }
    )

    assert device["device_id"] == "0x00158d0000000001"
    assert device["mqtt_topic"] == "zigbee2mqtt/kitchen_light"
    assert "state" in device["capabilities"]
    assert "brightness_percent" in device["capabilities"]
    assert "color_temperature_mired" in device["capabilities"]
    assert device["capability_metadata"]["brightness_percent"]["access"]["set"] is False
    assert device["capability_metadata"]["brightness_percent"]["access"]["get"] is True
    assert device["exposes"][1]["property"] == "brightness"


def test_normalizes_common_long_tail_sensor_exposes() -> None:
    device = normalize_zigbee2mqtt_device(
        {
            "friendly_name": "basement_sensor",
            "definition": {
                "exposes": [
                    {"property": "battery_low", "type": "binary", "access": 1},
                    {"property": "tamper", "type": "binary", "access": 1},
                    {"property": "water_leak", "type": "binary", "access": 1},
                    {"property": "voltage", "type": "numeric", "unit": "V", "access": 5},
                    {"property": "pressure", "type": "numeric", "unit": "hPa", "access": 5},
                ]
            },
        }
    )

    assert "battery_low" in device["capabilities"]
    assert "tamper" in device["capabilities"]
    assert "water_leak" in device["capabilities"]
    assert "voltage_v" in device["capabilities"]
    assert "pressure_hpa" in device["capabilities"]
    assert device["capability_metadata"]["voltage_v"]["unit"] == "V"
    assert device["capability_metadata"]["voltage_v"]["access"]["published"] is True
    assert device["capability_metadata"]["voltage_v"]["access"]["get"] is True


def test_available_commands_follow_capabilities() -> None:
    commands = available_commands_for(["state", "brightness_percent", "temperature_c"])
    command_ids = [command["id"] for command in commands]

    assert command_ids == ["refresh", "set_brightness", "set_state"]


def test_available_commands_require_writable_exposes_when_metadata_is_present() -> None:
    commands = available_commands_for(
        ["state", "brightness_percent", "color_temperature_mired"],
        [
            {"capability": "state", "access": {"set": True}},
            {"capability": "brightness_percent", "access": {"set": False}},
            {"capability": "color_temperature_mired", "access": {"set": True}},
        ],
    )

    assert [command["id"] for command in commands] == [
        "refresh",
        "set_color_temperature",
        "set_state",
    ]
