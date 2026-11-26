from __future__ import annotations

import pytest

from piphi_ble_gateway_sidecar import state


@pytest.fixture(autouse=True)
def reset_runtime_auth(monkeypatch):
    state.runtime.auth.update(container_id="", internal_token="")
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "test-token")
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
