from __future__ import annotations

from dataclasses import dataclass

from piphi_network_aqara.cloud.models import AqaraCloudDevice, AqaraResourceInfo, AqaraResourceValue


@dataclass(frozen=True, slots=True)
class AqaraDeviceSample:
    slug: str
    device: AqaraCloudDevice
    resources: tuple[AqaraResourceInfo, ...]
    values: tuple[AqaraResourceValue, ...]
    expected_state: dict[str, object]
    expected_commands: tuple[str, ...] = ()
    expected_default_widget: str = "sensor-card"


AQARA_DEVICE_SAMPLES: tuple[AqaraDeviceSample, ...] = (
    AqaraDeviceSample(
        slug="climate_sensor",
        device=AqaraCloudDevice(
            did="lumi.env.1001",
            name="Kitchen Climate",
            model="lumi.sensor_ht.agl02",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="0.1.85", name="Temperature value", description="Temperature value", access=3),
            AqaraResourceInfo(resource_id="0.2.85", name="Humidity value", description="Humidity value", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="0.1.85", value="23.1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="0.2.85", value="48", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.env.1001", resource_id="8.0.2008", value="91", timestamp_ms=1710000000000),
        ),
        expected_state={"temperature_c": 23.1, "humidity_percent": 48, "battery_percent": 91},
        expected_default_widget="room-climate-card",
    ),
    AqaraDeviceSample(
        slug="air_quality_monitor",
        device=AqaraCloudDevice(
            did="lumi.air.1010",
            name="Nursery Air",
            model="aqara.airmonitor.v1",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="0.1.85", name="Temperature value", description="Temperature value", access=3),
            AqaraResourceInfo(resource_id="0.2.85", name="Humidity value", description="Humidity value", access=3),
            AqaraResourceInfo(resource_id="0.5.85", name="CO2", description="CO2", access=3),
            AqaraResourceInfo(resource_id="0.6.85", name="TVOC", description="TVOC", access=3),
            AqaraResourceInfo(resource_id="0.7.85", name="PM2.5", description="Particulate Matter", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="0.1.85", value="21.3", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="0.2.85", value="45", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="0.5.85", value="612", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="0.6.85", value="55", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="0.7.85", value="14", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.air.1010", resource_id="8.0.2008", value="88", timestamp_ms=1710000000000),
        ),
        expected_state={
            "temperature_c": 21.3,
            "humidity_percent": 45,
            "co2_ppm": 612,
            "voc_ppb": 55,
            "pm25_ugm3": 14,
            "battery_percent": 88,
        },
        expected_default_widget="room-climate-card",
    ),
    AqaraDeviceSample(
        slug="presence_sensor",
        device=AqaraCloudDevice(
            did="lumi.motion.1002",
            name="Hall Motion",
            model="aqara.motion.fp1e",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="2.1.85", name="presence", description="presence", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.motion.1002", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.motion.1002", resource_id="8.0.2008", value="76", timestamp_ms=1710000000000),
        ),
        expected_state={"presence_detected": True, "battery_percent": 76},
        expected_default_widget="presence-card",
    ),
    AqaraDeviceSample(
        slug="contact_sensor",
        device=AqaraCloudDevice(
            did="lumi.contact.1003",
            name="Front Window",
            model="lumi.sensor_magnet.acn001",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="3.1.85", name="contact", description="door/window contact", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.contact.1003", resource_id="3.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.contact.1003", resource_id="8.0.2008", value="67", timestamp_ms=1710000000000),
        ),
        expected_state={"contact_open": True, "battery_percent": 67},
    ),
    AqaraDeviceSample(
        slug="leak_sensor",
        device=AqaraCloudDevice(
            did="lumi.leak.1004",
            name="Basement Leak",
            model="aqara.water.wleak01",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="3.2.85", name="water leak", description="water leak", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.leak.1004", resource_id="3.2.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.leak.1004", resource_id="8.0.2008", value="83", timestamp_ms=1710000000000),
        ),
        expected_state={"leak_detected": False, "battery_percent": 83},
        expected_default_widget="safety-overview-card",
    ),
    AqaraDeviceSample(
        slug="smoke_sensor",
        device=AqaraCloudDevice(
            did="lumi.smoke.1005",
            name="Hall Smoke Alarm",
            model="aqara.smoke.acn03",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="3.3.85", name="smoke alarm", description="smoke alarm", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.smoke.1005", resource_id="3.3.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.smoke.1005", resource_id="8.0.2008", value="80", timestamp_ms=1710000000000),
        ),
        expected_state={"smoke_alarm": True, "battery_percent": 80},
        expected_default_widget="safety-overview-card",
    ),
    AqaraDeviceSample(
        slug="gas_sensor",
        device=AqaraCloudDevice(
            did="lumi.gas.1006",
            name="Kitchen Gas Alarm",
            model="aqara.gas.acn02",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="3.4.85", name="natural gas", description="natural gas alarm", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.gas.1006", resource_id="3.4.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.gas.1006", resource_id="8.0.2008", value="72", timestamp_ms=1710000000000),
        ),
        expected_state={"gas_alarm": True, "battery_percent": 72},
        expected_default_widget="safety-overview-card",
    ),
    AqaraDeviceSample(
        slug="smart_plug",
        device=AqaraCloudDevice(
            did="lumi.plug.1007",
            name="Desk Plug",
            model="lumi.plug.maus01",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="4.1.85", name="plug status", description="plug status", access=5),
            AqaraResourceInfo(resource_id="8.0.2001", name="Load power", description="Load power", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.plug.1007", resource_id="4.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.plug.1007", resource_id="8.0.2001", value="12.4", timestamp_ms=1710000000000),
        ),
        expected_state={"switch_on": False, "power_w": 12.4},
        expected_commands=("turn_on", "turn_off"),
        expected_default_widget="tile",
    ),
    AqaraDeviceSample(
        slug="energy_plug",
        device=AqaraCloudDevice(
            did="lumi.energy.1014",
            name="Washer Plug",
            model="aqara.plug.usb01",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="4.1.85", name="plug status", description="plug status", access=5),
            AqaraResourceInfo(resource_id="8.0.2001", name="Load power", description="Load power", access=3),
            AqaraResourceInfo(resource_id="8.0.2002", name="Power consumption", description="Power consumption", access=3),
            AqaraResourceInfo(resource_id="8.0.2004", name="Line voltage", description="Line voltage", access=3),
            AqaraResourceInfo(resource_id="8.0.2005", name="Load current", description="Load current", access=3),
            AqaraResourceInfo(resource_id="8.0.2006", name="Line frequency", description="Line frequency", access=3),
            AqaraResourceInfo(resource_id="8.0.2007", name="Power factor", description="Power factor", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="4.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2001", value="623.5", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2002", value="1.72", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2004", value="121.6", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2005", value="5.13", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2006", value="60", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.energy.1014", resource_id="8.0.2007", value="0.98", timestamp_ms=1710000000000),
        ),
        expected_state={
            "switch_on": True,
            "power_w": 623.5,
            "energy_kwh": 1.72,
            "voltage_v": 121.6,
            "current_a": 5.13,
            "frequency_hz": 60,
            "power_factor": 0.98,
        },
        expected_commands=("turn_on", "turn_off"),
        expected_default_widget="tile",
    ),
    AqaraDeviceSample(
        slug="dimmable_light",
        device=AqaraCloudDevice(
            did="lumi.light.1011",
            name="Bedroom Lamp",
            model="aqara.light.bulb_e27",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="4.1.85", name="Light switch", description="light switch", access=5),
            AqaraResourceInfo(resource_id="5.1.85", name="Brightness value", description="brightness level", access=5),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.light.1011", resource_id="4.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="lumi.light.1011", resource_id="5.1.85", value="64", timestamp_ms=1710000000000),
        ),
        expected_state={"switch_on": True, "brightness_percent": 64},
        expected_commands=("turn_on", "turn_off", "set_brightness"),
        expected_default_widget="light-card",
    ),
    AqaraDeviceSample(
        slug="camera_hub",
        device=AqaraCloudDevice(
            did="aqara.camera.1013",
            name="Nursery Camera",
            model="aqara.camera.g3",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="2.1.85", name="Camera motion", description="camera motion detected", access=3),
            AqaraResourceInfo(resource_id="2.2.85", name="Person detected", description="person detected", access=3),
            AqaraResourceInfo(resource_id="2.3.85", name="Audio detected", description="audio detected", access=3),
            AqaraResourceInfo(resource_id="7.1.85", name="Privacy mode", description="camera privacy mode", access=3),
            AqaraResourceInfo(resource_id="7.2.85", name="Recording", description="sd recording switch", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.2.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="2.3.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.camera.1013", resource_id="7.2.85", value="1", timestamp_ms=1710000000000),
        ),
        expected_state={
            "motion_detected": True,
            "person_detected": True,
            "audio_detected": False,
            "privacy_mode": False,
            "recording_enabled": True,
        },
        expected_default_widget="camera",
    ),
    AqaraDeviceSample(
        slug="doorbell_camera",
        device=AqaraCloudDevice(
            did="aqara.doorbell.1015",
            name="Front Doorbell",
            model="aqara.doorbell.g4",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="2.4.85", name="Doorbell ring", description="doorbell ring event", access=3),
            AqaraResourceInfo(resource_id="2.5.85", name="Person detected", description="human detected", access=3),
            AqaraResourceInfo(resource_id="8.0.2010", name="Low battery alarm", description="low battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="2.4.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="2.5.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.doorbell.1015", resource_id="8.0.2010", value="0", timestamp_ms=1710000000000),
        ),
        expected_state={"doorbell_pressed": True, "person_detected": True, "battery_low": False},
        expected_default_widget="camera",
    ),
    AqaraDeviceSample(
        slug="curtain_motor",
        device=AqaraCloudDevice(
            did="lumi.cover.1008",
            name="Living Room Curtain",
            model="lumi.curtain.acn002",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="14.7.111", name="position", description="position", access=5),
        ),
        values=(
            AqaraResourceValue(subject_id="lumi.cover.1008", resource_id="14.7.111", value="34", timestamp_ms=1710000000000),
        ),
        expected_state={"cover_position": 34},
        expected_commands=("open", "close", "set_position"),
        expected_default_widget="cover-card",
    ),
    AqaraDeviceSample(
        slug="door_lock",
        device=AqaraCloudDevice(
            did="aqara.lock.1009",
            name="Front Door Lock",
            model="aqara.lock.u100",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="6.1.85", name="lock status", description="door lock status", access=3),
            AqaraResourceInfo(resource_id="3.1.185", name="door contact", description="door contact", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="aqara.lock.1009", resource_id="6.1.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1009", resource_id="3.1.185", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1009", resource_id="8.0.2008", value="58", timestamp_ms=1710000000000),
        ),
        expected_state={"locked": True, "contact_open": False, "battery_percent": 58},
        expected_default_widget="access-control-card",
    ),
    AqaraDeviceSample(
        slug="door_lock_advanced",
        device=AqaraCloudDevice(
            did="aqara.lock.1012",
            name="Side Door Lock",
            model="aqara.lock.d200",
            state=1,
        ),
        resources=(
            AqaraResourceInfo(resource_id="6.1.85", name="lock status", description="door lock status", access=3),
            AqaraResourceInfo(resource_id="3.1.185", name="door contact", description="door contact", access=3),
            AqaraResourceInfo(resource_id="6.2.85", name="Tamper alarm", description="forced entry tamper alarm", access=3),
            AqaraResourceInfo(resource_id="6.3.85", name="Lock jam alarm", description="lock jam alarm", access=3),
            AqaraResourceInfo(resource_id="8.0.2010", name="Low battery alarm", description="low battery", access=3),
            AqaraResourceInfo(resource_id="8.0.2008", name="battery", description="battery", access=3),
        ),
        values=(
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="6.1.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="3.1.185", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="6.2.85", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="6.3.85", value="0", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="8.0.2010", value="1", timestamp_ms=1710000000000),
            AqaraResourceValue(subject_id="aqara.lock.1012", resource_id="8.0.2008", value="41", timestamp_ms=1710000000000),
        ),
        expected_state={
            "locked": False,
            "contact_open": True,
            "battery_low": True,
            "tamper_detected": True,
            "lock_jammed": False,
            "battery_percent": 41,
        },
        expected_default_widget="access-control-card",
    ),
)
