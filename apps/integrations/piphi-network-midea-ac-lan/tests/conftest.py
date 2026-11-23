from __future__ import annotations

import pytest

from piphi_network_midea_ac_lan import state


class DefaultFakeClient:
    hardware_id = "midea-test"

    def __init__(self) -> None:
        self.closed = False
        self.snapshot = {
            "connected": True,
            "power": True,
            "hvac_mode": "cool",
            "hvac_action": "cooling",
            "target_temperature_c": 22.0,
            "indoor_temperature_c": 24.0,
            "fan_mode": "auto",
            "swing_mode": "off",
            "preset_mode": "none",
        }

    async def refresh(self) -> dict:
        return dict(self.snapshot)

    async def execute(self, command: str, args: dict) -> dict:
        if command == "set_power":
            self.snapshot["power"] = args["power"]
        return dict(self.snapshot)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")

    async def connect(**_kwargs):
        return DefaultFakeClient()

    state.runtime_data.connector = connect
    yield
    state.runtime_data.connector = state.MideaLanClient.connect


@pytest.fixture(autouse=True)
def reset_runtime_state():
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
    state.runtime_data.configs.clear()
    state.runtime_data.clients.clear()
    state.runtime_data.locks.clear()
    yield
    state.runtime_data.configs.clear()
    state.runtime_data.clients.clear()
    state.runtime_data.locks.clear()
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
