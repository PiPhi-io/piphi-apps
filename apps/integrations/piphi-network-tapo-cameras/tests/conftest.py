from __future__ import annotations

import pytest

from piphi_network_tapo_cameras.state import registry, runtime_data
from piphi_network_tapo_cameras.tapo_client import TapoClient


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")


@pytest.fixture(autouse=True)
def reset_runtime_state():
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime_data.configs.clear()
    runtime_data.clients.clear()
    runtime_data.locks.clear()
    runtime_data.connector = TapoClient.connect
    yield
    runtime_data.configs.clear()
    runtime_data.clients.clear()
    runtime_data.locks.clear()
    runtime_data.connector = TapoClient.connect
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
