from __future__ import annotations

from enum import Enum

import pytest

from piphi_network_midea_ac_lan.midea_client import MideaLanClient


class OperationalMode(Enum):
    AUTO = 1
    COOL = 2
    HEAT = 3
    DRY = 4
    FAN_ONLY = 5


class FanSpeed(Enum):
    SILENT = 20
    LOW = 40
    MEDIUM = 60
    HIGH = 80
    MAX = 100
    AUTO = 102


class SwingMode(Enum):
    OFF = 0
    HORIZONTAL = 3
    VERTICAL = 12
    BOTH = 15


class FakeDevice:
    OperationalMode = OperationalMode
    FanSpeed = FanSpeed
    SwingMode = SwingMode

    def __init__(self) -> None:
        self.online = True
        self.power_state = True
        self.operational_mode = OperationalMode.COOL
        self.supported_operation_modes = list(OperationalMode)
        self.target_temperature = 22.5
        self.indoor_temperature = 24.0
        self.outdoor_temperature = 31.0
        self.fan_speed = FanSpeed.MEDIUM
        self.supported_fan_speeds = [FanSpeed.AUTO, FanSpeed.MEDIUM, FanSpeed.HIGH]
        self.swing_mode = SwingMode.OFF
        self.supported_swing_modes = [SwingMode.OFF, SwingMode.BOTH]
        self.supports_eco = True
        self.supports_turbo = True
        self.supports_freeze_protection = False
        self.eco = False
        self.turbo = False
        self.freeze_protection = False
        self.sleep = False
        self.min_target_temperature = 16
        self.max_target_temperature = 30
        self.beep = True
        self.apply_calls = 0
        self.refresh_calls = 0

    async def apply(self) -> None:
        self.apply_calls += 1

    async def refresh(self) -> None:
        self.refresh_calls += 1


def test_snapshot_normalizes_common_climate_state() -> None:
    state = MideaLanClient(FakeDevice()).snapshot()
    assert state == {
        "connected": True,
        "power": True,
        "hvac_mode": "cool",
        "hvac_action": "cooling",
        "target_temperature_c": 22.5,
        "indoor_temperature_c": 24.0,
        "outdoor_temperature_c": 31.0,
        "fan_speed_percent": 60.0,
        "fan_mode": "medium",
        "fan_modes_supported": "auto,medium,high",
        "swing_mode": "off",
        "swing_modes_supported": "off,both",
        "preset_mode": "none",
        "preset_modes_supported": "none,sleep,eco,boost",
    }


@pytest.mark.anyio
async def test_commands_apply_then_read_back_device_state() -> None:
    device = FakeDevice()
    client = MideaLanClient(device)

    power = await client.execute("set_power", {"power": False})
    mode = await client.execute("set_hvac_mode", {"mode": "heat"})
    target = await client.execute("set_target_temperature", {"temperature": 23.5})
    fan = await client.execute("set_fan_mode", {"fan_mode": "high"})
    swing = await client.execute("set_swing_mode", {"swing_mode": "both"})
    preset = await client.execute("set_preset_mode", {"preset_mode": "boost"})

    assert power["power"] is False
    assert mode["hvac_mode"] == "heat"
    assert target["target_temperature_c"] == 23.5
    assert fan["fan_mode"] == "high"
    assert swing["swing_mode"] == "both"
    assert preset["preset_mode"] == "boost"
    assert device.apply_calls == 6
    assert device.refresh_calls == 6
    assert device.beep is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("command", "args", "message"),
    [
        ("set_power", {"power": "yes"}, "boolean"),
        ("set_hvac_mode", {"mode": "turbo"}, "Unsupported HVAC mode"),
        ("set_target_temperature", {"temperature": 42}, "between 16 and 30"),
        ("set_fan_mode", {"fan_mode": "turbo"}, "Unsupported fan mode"),
        ("set_fan_mode", {"fan_mode": "low"}, "not supported"),
        ("set_swing_mode", {"swing_mode": "diagonal"}, "Unsupported swing mode"),
        ("set_swing_mode", {"swing_mode": "vertical"}, "not supported"),
        ("set_preset_mode", {"preset_mode": "party"}, "Unsupported preset mode"),
        ("set_preset_mode", {"preset_mode": "away"}, "not supported"),
    ],
)
async def test_commands_reject_invalid_values(command: str, args: dict, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        await MideaLanClient(FakeDevice()).execute(command, args)


@pytest.mark.anyio
async def test_commands_reject_model_or_mode_incompatible_options() -> None:
    device = FakeDevice()
    device.supported_operation_modes = [OperationalMode.AUTO, OperationalMode.COOL]
    client = MideaLanClient(device)
    with pytest.raises(ValueError, match="HVAC mode is not supported"):
        await client.execute("set_hvac_mode", {"mode": "heat"})
    device.operational_mode = OperationalMode.FAN_ONLY
    with pytest.raises(ValueError, match="not available in fan_only mode"):
        await client.execute("set_preset_mode", {"preset_mode": "sleep"})


def test_hvac_action_is_derived_and_never_presented_as_direct_device_state() -> None:
    device = FakeDevice()
    client = MideaLanClient(device)
    assert client.snapshot()["hvac_action"] == "cooling"
    device.target_temperature = 24
    assert client.snapshot()["hvac_action"] == "idle"
    device.operational_mode = OperationalMode.HEAT
    device.target_temperature = 26
    assert client.snapshot()["hvac_action"] == "heating"
    device.power_state = False
    assert client.snapshot()["hvac_action"] == "off"
