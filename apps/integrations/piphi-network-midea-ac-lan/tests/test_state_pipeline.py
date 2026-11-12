from __future__ import annotations

import pytest

from piphi_network_midea_ac_lan import state
from piphi_network_midea_ac_lan.schemas import DeviceConfig


class FakeClient:
    def __init__(self) -> None:
        self.snapshot = {
            "connected": True,
            "power": True,
            "hvac_mode": "cool",
            "hvac_action": "cooling",
            "target_temperature_c": 22.0,
            "indoor_temperature_c": 24.5,
            "outdoor_temperature_c": 30.0,
            "fan_speed_percent": 40.0,
            "fan_mode": "low",
            "fan_modes_supported": "auto,low,high",
            "swing_mode": "off",
            "swing_modes_supported": "off,both",
            "preset_mode": "none",
            "preset_modes_supported": "none,sleep,eco,boost",
        }

    async def refresh(self) -> dict:
        return dict(self.snapshot)

    async def execute(self, command: str, args: dict) -> dict:
        if command == "set_power":
            self.snapshot["power"] = args["power"]
        elif command == "set_hvac_mode":
            self.snapshot["hvac_mode"] = args["mode"]
        elif command == "set_target_temperature":
            self.snapshot["target_temperature_c"] = args["temperature"]
        elif command == "set_fan_mode":
            self.snapshot["fan_mode"] = args["fan_mode"]
        elif command == "set_swing_mode":
            self.snapshot["swing_mode"] = args["swing_mode"]
        elif command == "set_preset_mode":
            self.snapshot["preset_mode"] = args["preset_mode"]
        return dict(self.snapshot)


@pytest.mark.anyio
async def test_runtime_publishes_real_state_and_keeps_credentials_private(monkeypatch) -> None:
    fake = FakeClient()
    connector_calls: list[dict] = []

    async def connect(**kwargs):
        connector_calls.append(kwargs)
        return fake

    monkeypatch.setattr(state, "_client_connector", connect)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **kwargs: None)
    config = DeviceConfig(
        id="midea-pipeline-test",
        host="192.0.2.10",
        midea_device_id=12345,
        token="private-token",
        key="private-key",
        controls_enabled=True,
    )
    await state.apply_config(config)
    try:
        entry = state.registry.get(config.id)
        assert entry is not None
        assert "token" not in entry["config"]
        assert "key" not in entry["config"]

        refreshed = await state.refresh_entry(entry)
        changed = await state.execute_command(
            entry, "set_target_temperature", {"temperature": 23.5}
        )
        await state.execute_command(entry, "set_fan_mode", {"fan_mode": "high"})
        await state.execute_command(entry, "set_swing_mode", {"swing_mode": "both"})
        changed = await state.execute_command(
            entry, "set_preset_mode", {"preset_mode": "sleep"}
        )

        assert refreshed["indoor_temperature_c"] == 24.5
        assert changed["target_temperature_c"] == 23.5
        assert changed["fan_mode"] == "high"
        assert changed["swing_mode"] == "both"
        assert changed["preset_mode"] == "sleep"
        assert state.registry.state_snapshots[config.id]["state"] == changed
        assert connector_calls == [{
            "host": "192.0.2.10",
            "port": 6444,
            "device_id": 12345,
            "token": "private-token",
            "key": "private-key",
        }]
    finally:
        await state.remove_config(config.id)


@pytest.mark.anyio
async def test_mutations_are_disabled_until_explicitly_enabled() -> None:
    config = DeviceConfig(id="midea-controls-off-test", host="192.0.2.11")
    await state.apply_config(config)
    try:
        entry = state.registry.get(config.id)
        assert entry is not None
        with pytest.raises(ValueError, match="controls are disabled"):
            await state.execute_command(entry, "set_power", {"power": True})
    finally:
        await state.remove_config(config.id)
