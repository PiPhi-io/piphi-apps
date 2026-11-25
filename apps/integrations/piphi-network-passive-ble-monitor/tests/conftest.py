from __future__ import annotations

import pytest

from piphi_network_passive_ble_monitor import state
from piphi_network_passive_ble_monitor.gateway import ObservationPage


class EmptyGateway:
    async def register(self, consumer_id: str, handle: str) -> None:
        return None

    async def unregister(self, consumer_id: str) -> None:
        return None

    async def snapshot(self, consumer_id: str, *, after: int = 0) -> ObservationPage:
        return ObservationPage((), after, True)

    async def observations(self, consumer_id: str, *, after: int) -> ObservationPage:
        return ObservationPage((), after, True)

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def no_external_gateway(monkeypatch, tmp_path):
    monkeypatch.setattr(state, "gateway_client", lambda _config: EmptyGateway())
    monkeypatch.setenv("PIPHI_BLE_MONITOR_STATE_PATH", str(tmp_path / "state.json"))
    state._persisted_state.clear()
    state.runtime.auth.update(container_id="", internal_token="")
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "test-token")
