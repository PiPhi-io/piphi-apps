from __future__ import annotations

import pytest

from aqara_device_samples import AQARA_DEVICE_SAMPLES
from piphi_network_aqara.cloud.models import AqaraResourceInfo, AqaraResourceValue, AqaraTraitInfo, AqaraTraitValue
from piphi_network_aqara.runtime import _build_snapshot, _capability_widgets, _filter_available_dynamic_endpoints


@pytest.mark.parametrize("sample", AQARA_DEVICE_SAMPLES, ids=lambda sample: sample.slug)
def test_build_snapshot_maps_supported_device_family_samples(sample) -> None:
    entry = {
        "did": sample.device.did,
        "device_model": sample.device.model,
        "device_name": sample.device.name,
        "device_state": sample.device.state,
    }

    snapshot = _build_snapshot(entry=entry, resources=list(sample.resources), values=list(sample.values))
    state = snapshot["state"]

    for key, expected_value in sample.expected_state.items():
        assert state[key] == expected_value
    for command_id in sample.expected_commands:
        assert command_id in snapshot["command_bindings"]


def test_build_snapshot_maps_supported_resource_variants() -> None:
    entry = {
        "did": "lumi.multi.9999",
        "device_model": "aqara.sensor.multi",
        "device_name": "Multi Sensor",
        "device_state": 1,
    }
    resources = [
        AqaraResourceInfo(resource_id="0.1.85", name="Temperature value", description="Temperature value", access=3),
        AqaraResourceInfo(resource_id="0.2.85", name="Humidity value", description="Humidity value", access=3),
        AqaraResourceInfo(resource_id="0.3.85", name="Pressure value", description="Pressure value", access=3),
        AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        AqaraResourceInfo(resource_id="8.0.2010", name="Low battery alarm", description="low battery", access=3),
        AqaraResourceInfo(resource_id="0.4.85", name="Lux", description="Lux", access=3),
        AqaraResourceInfo(resource_id="2.1.85", name="motion", description="motion", access=3),
        AqaraResourceInfo(resource_id="2.2.85", name="presence", description="presence", access=3),
        AqaraResourceInfo(resource_id="2.3.85", name="Person detected", description="person detected", access=3),
        AqaraResourceInfo(resource_id="2.4.85", name="Audio detected", description="audio detected", access=3),
        AqaraResourceInfo(resource_id="2.5.85", name="Doorbell ring", description="doorbell ring", access=3),
        AqaraResourceInfo(resource_id="3.1.85", name="contact", description="door/window contact", access=3),
        AqaraResourceInfo(resource_id="3.2.85", name="water leak", description="water leak", access=3),
        AqaraResourceInfo(resource_id="3.3.85", name="smoke alarm", description="smoke alarm", access=3),
        AqaraResourceInfo(resource_id="3.4.85", name="natural gas", description="natural gas alarm", access=3),
        AqaraResourceInfo(resource_id="0.5.85", name="CO2", description="CO2", access=3),
        AqaraResourceInfo(resource_id="0.6.85", name="TVOC", description="TVOC", access=3),
        AqaraResourceInfo(resource_id="0.7.85", name="PM2.5", description="Particulate Matter", access=3),
        AqaraResourceInfo(resource_id="4.1.85", name="plug status", description="plug status", access=5),
        AqaraResourceInfo(resource_id="8.0.2001", name="Load power", description="Load power", access=3),
        AqaraResourceInfo(resource_id="8.0.2002", name="Power consumption", description="Power consumption", access=3),
        AqaraResourceInfo(resource_id="8.0.2004", name="Line voltage", description="Line voltage", access=3),
        AqaraResourceInfo(resource_id="8.0.2005", name="Load current", description="Load current", access=3),
        AqaraResourceInfo(resource_id="8.0.2006", name="Line frequency", description="Line frequency", access=3),
        AqaraResourceInfo(resource_id="8.0.2007", name="Power factor", description="Power factor", access=3),
        AqaraResourceInfo(resource_id="5.1.85", name="brightness", description="brightness", access=3),
        AqaraResourceInfo(resource_id="5.2.85", name="ColorTemperature", access=5, min_value=153, max_value=500),
        AqaraResourceInfo(resource_id="0.8.85", name="SetTemperature", access=5, min_value=5, max_value=30),
        AqaraResourceInfo(resource_id="4.2.85", name="FanSpeed", access=5, min_value=0, max_value=100),
        AqaraResourceInfo(resource_id="14.7.111", name="cover position", description="cover position", access=5),
        AqaraResourceInfo(resource_id="6.1.85", name="lock status", description="door lock status", access=3),
        AqaraResourceInfo(resource_id="6.2.85", name="tamper alarm", description="tamper alarm", access=3),
        AqaraResourceInfo(resource_id="6.3.85", name="lock jam alarm", description="lock jam alarm", access=3),
    ]
    values = [
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.1.85", value="22.8", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.2.85", value="43", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.3.85", value="1012", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2008", value="88", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2010", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.4.85", value="175", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="2.2.85", value="0", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="2.3.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="2.4.85", value="0", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="2.5.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="3.1.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="3.2.85", value="0", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="3.3.85", value="0", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="3.4.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.5.85", value="612", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.6.85", value="55", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.7.85", value="14", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="4.1.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2001", value="623.5", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2002", value="1.72", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2004", value="121.6", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2005", value="5.13", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2006", value="60", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="8.0.2007", value="0.98", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="5.1.85", value="64", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="5.2.85", value="250", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="0.8.85", value="21.5", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="4.2.85", value="40", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="14.7.111", value="35", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="6.1.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="6.2.85", value="1", timestamp_ms=1710000000000),
        AqaraResourceValue(subject_id="lumi.multi.9999", resource_id="6.3.85", value="0", timestamp_ms=1710000000000),
    ]

    snapshot = _build_snapshot(entry=entry, resources=resources, values=values)
    state = snapshot["state"]

    assert state["temperature_c"] == 22.8
    assert state["humidity_percent"] == 43
    assert state["pressure_hpa"] == 1012
    assert state["battery_percent"] == 88
    assert state["battery_low"] is True
    assert state["illuminance_lux"] == 175
    assert state["motion_detected"] is True
    assert state["presence_detected"] is False
    assert state["person_detected"] is True
    assert state["audio_detected"] is False
    assert state["doorbell_pressed"] is True
    assert state["contact_open"] is True
    assert state["leak_detected"] is False
    assert state["smoke_alarm"] is False
    assert state["gas_alarm"] is True
    assert state["co2_ppm"] == 612
    assert state["voc_ppb"] == 55
    assert state["pm25_ugm3"] == 14
    assert state["switch_on"] is True
    assert state["power_w"] == 623.5
    assert state["energy_kwh"] == 1.72
    assert state["voltage_v"] == 121.6
    assert state["current_a"] == 5.13
    assert state["frequency_hz"] == 60
    assert state["power_factor"] == 0.98
    assert state["brightness_percent"] == 64
    assert state["color_temperature"] == 250
    assert state["target_temperature_c"] == 21.5
    assert state["fan_speed_percent"] == 40
    assert state["cover_position"] == 35
    assert state["locked"] is True
    assert state["tamper_detected"] is True
    assert state["lock_jammed"] is False
    assert "turn_on" in snapshot["command_bindings"]
    assert "set_position" in snapshot["command_bindings"]
    assert "set_color_temperature" in snapshot["command_bindings"]
    assert "set_temperature" in snapshot["command_bindings"]
    assert "set_fan_speed" in snapshot["command_bindings"]


def test_build_snapshot_negotiates_separate_read_and_write_resources() -> None:
    entry = {
        "did": "lumi.cover.split",
        "device_model": "lumi.curtain.split",
        "device_name": "Split resource curtain",
        "device_state": 1,
    }
    resources = [
        AqaraResourceInfo(
            resource_id="14.1.85",
            name="CurrentPositionPercentage",
            description="Current cover position",
            access=3,
            min_value=0,
            max_value=100,
        ),
        AqaraResourceInfo(
            resource_id="14.2.85",
            name="TargetPositionPercentage",
            description="Target cover position",
            access=6,
            min_value=0,
            max_value=100,
        ),
    ]
    values = [
        AqaraResourceValue(
            subject_id="lumi.cover.split",
            resource_id="14.1.85",
            value="35",
            timestamp_ms=1710000000000,
        )
    ]

    snapshot = _build_snapshot(entry=entry, resources=resources, values=values)

    assert snapshot["state"]["cover_position"] == 35
    assert snapshot["command_bindings"]["set_position"]["resource_id"] == "14.2.85"
    assert snapshot["command_bindings"]["open"]["resource_id"] == "14.2.85"


def test_build_snapshot_negotiates_trait_modes_and_movement_state() -> None:
    entry = {
        "did": "lumi.airrtc.traits",
        "device_model": "lumi.airrtc.aeu001",
        "device_name": "Trait thermostat",
        "device_state": 1,
    }
    definitions = [
        AqaraTraitInfo(
            endpoint_id=1,
            function_code="Thermostat",
            trait_code="HeaterCoolerMode",
            readable=True,
            writable=True,
            supported_values={"Off": "0", "Heat": "1", "Auto Heat": "2"},
        ),
        AqaraTraitInfo(
            endpoint_id=1,
            function_code="Thermostat",
            trait_code="FanMode",
            readable=True,
            writable=True,
            supported_values={"Auto": "0", "Low": "1", "High": "2"},
        ),
        AqaraTraitInfo(
            endpoint_id=1,
            function_code="Thermostat",
            trait_code="RockSetting",
            readable=True,
            writable=True,
            supported_values={"Off": "0", "Vertical": "1"},
        ),
        AqaraTraitInfo(
            endpoint_id=1,
            function_code="Thermostat",
            trait_code="AirflowDirection",
            readable=True,
            writable=True,
            supported_values={"Horizontal": "0", "Vertical": "1"},
        ),
        AqaraTraitInfo(
            endpoint_id=2,
            function_code="WindowCovering",
            trait_code="MotorOperationStatus",
            readable=True,
            supported_values={"Stopped": "0", "Opening": "1", "Closing": "2"},
        ),
    ]
    values = [
        AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="HeaterCoolerMode", value="1"),
        AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="FanMode", value="0"),
        AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="RockSetting", value="1"),
        AqaraTraitValue(endpoint_id=1, function_code="Thermostat", trait_code="AirflowDirection", value="0"),
        AqaraTraitValue(endpoint_id=2, function_code="WindowCovering", trait_code="MotorOperationStatus", value="2"),
    ]

    snapshot = _build_snapshot(entry=entry, resources=[], values=[], traits=definitions, trait_values=values)

    assert snapshot["state"] == {
        "sampled_at": snapshot["state"]["sampled_at"],
        "connected": True,
        "did": "lumi.airrtc.traits",
        "device_model": "lumi.airrtc.aeu001",
        "name": "Trait thermostat",
        "last_error": None,
        "raw_resources": {},
        "raw_resource_timestamps_ms": {},
        "hvac_mode": "heat",
        "fan_mode": "auto",
        "swing_mode": "vertical",
        "airflow_direction": "horizontal",
        "cover_movement_state": "closing",
    }
    assert snapshot["command_bindings"]["set_hvac_mode"]["enum_values"] == {
        "off": "0",
        "heat": "1",
        "auto_heat": "2",
    }
    assert {"set_hvac_mode", "set_fan_mode", "set_swing_mode", "set_airflow_direction"} <= set(
        snapshot["command_bindings"]
    )


def test_trait_enum_actions_fail_closed_for_ambiguous_metadata() -> None:
    snapshot = _build_snapshot(
        entry={"did": "lumi.ambiguous", "device_model": "lumi.airrtc.ambiguous", "device_name": "Ambiguous", "device_state": 1},
        resources=[],
        values=[],
        traits=[
            AqaraTraitInfo(
                endpoint_id=1,
                function_code="Thermostat",
                trait_code="HeaterCoolerMode",
                writable=True,
                supported_values={"Heat": "1", "Heating": "1"},
            )
        ],
        trait_values=[],
    )
    assert "set_hvac_mode" not in snapshot["command_bindings"]


def test_dynamic_endpoint_metadata_filters_unavailable_controls() -> None:
    traits = [
        AqaraTraitInfo(
            endpoint_id=0,
            function_code="Descriptor",
            trait_code="SupportedEndpointDynamic",
            readable=True,
            default_value="1",
        ),
        AqaraTraitInfo(endpoint_id=0, function_code="Descriptor", trait_code="EndpointArrayDynamic", readable=True),
        AqaraTraitInfo(
            endpoint_id=1,
            function_code="Thermostat",
            trait_code="HeaterCoolerMode",
            writable=True,
            supported_values={"Off": "0", "Heat": "1"},
        ),
        AqaraTraitInfo(
            endpoint_id=2,
            function_code="Thermostat",
            trait_code="HeaterCoolerMode",
            writable=True,
            supported_values={"Off": "0", "Cool": "2"},
        ),
    ]
    filtered = _filter_available_dynamic_endpoints(
        traits,
        [
            AqaraTraitValue(
                endpoint_id=0,
                function_code="Descriptor",
                trait_code="EndpointArrayDynamic",
                value="[0,2]",
            )
        ],
    )
    assert {trait.endpoint_id for trait in filtered} == {0, 2}

    malformed = _filter_available_dynamic_endpoints(
        traits,
        [
            AqaraTraitValue(
                endpoint_id=0,
                function_code="Descriptor",
                trait_code="EndpointArrayDynamic",
                value="not-json",
            )
        ],
    )
    assert {trait.endpoint_id for trait in malformed} == {0}

    ambiguous_snapshot = _build_snapshot(
        entry={"did": "lumi.dynamic", "device_model": "lumi.airrtc.dynamic", "device_name": "Dynamic", "device_state": 1},
        resources=[],
        values=[],
        traits=traits,
        trait_values=[],
    )
    assert "set_hvac_mode" not in ambiguous_snapshot["command_bindings"]


def test_cover_stop_requires_explicit_resource_enum() -> None:
    entry = {"did": "lumi.cover.stop", "device_model": "lumi.curtain.stop", "device_name": "Curtain", "device_state": 1}
    resources = [
        AqaraResourceInfo(
            resource_id="14.3.85",
            name="Curtain motor control",
            access=4,
            enums='[{"key":"Open","value":"1"},{"key":"Close","value":"2"},{"key":"Stop","value":"3"}]',
        )
    ]
    snapshot = _build_snapshot(entry=entry, resources=resources, values=[])
    assert snapshot["command_bindings"]["stop_cover"] == {"resource_id": "14.3.85", "value": "3"}


@pytest.mark.parametrize(
    ("capabilities", "expected_default_widget"),
    (
        (["temperature_c", "humidity_percent"], "room-climate-card"),
        (["temperature_c", "humidity_percent", "co2_ppm"], "room-climate-card"),
        (["locked", "contact_open"], "access-control-card"),
        (["tamper_detected"], "access-control-card"),
        (["privacy_mode", "motion_detected"], "camera"),
        (["doorbell_pressed", "person_detected"], "camera"),
        (["battery_low"], "device-health-card"),
        (["power_w"], "stat"),
        (["voltage_v"], "stat"),
        (["frequency_hz"], "stat"),
        (["smoke_alarm"], "safety-overview-card"),
        (["switch_on", "brightness_percent"], "light-card"),
        (["switch_on", "power_w", "voltage_v", "frequency_hz"], "tile"),
        (["presence_detected"], "presence-card"),
    ),
)
def test_capability_widgets_prefers_phase_two_dashboard_cards(
    capabilities: list[str],
    expected_default_widget: str,
) -> None:
    widgets = _capability_widgets(capabilities)
    assert widgets[0] == expected_default_widget
