from __future__ import annotations

from typing import ClassVar

import pytest


@pytest.fixture(autouse=True)
def allow_test_runtime_auth(monkeypatch):
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    yield
    from piphi_network_bambu_lab import state

    for session in list(state._sessions.values()):
        session.stop()
    state._sessions.clear()
    state._reports.clear()
    state.runtime_data.configs.clear()
    state.runtime_data.failures.clear()
    state.runtime_data.locks.clear()
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()


@pytest.fixture
def mock_mqtt(monkeypatch):
    from piphi_network_bambu_lab import state

    class FakeSession:
        instances: ClassVar[list[FakeSession]] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.connected = False
            self.stopped = False
            self.requests = 0
            self.instances.append(self)

        def start(self):
            self.connected = True

        def stop(self):
            self.stopped = True
            self.connected = False

        async def wait_ready(self):
            if not self.connected:
                raise ConnectionError("fake transport stopped")

        def request_full_status(self):
            self.requests += 1
            return self.connected

    monkeypatch.setattr(state, "PrinterMqttSession", FakeSession)
    return FakeSession
