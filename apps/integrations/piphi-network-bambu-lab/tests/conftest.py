from __future__ import annotations

import pytest


@pytest.fixture
def mock_mqtt(monkeypatch):
    from piphi_network_bambu_lab import state

    class FakeSession:
        instances: list[FakeSession] = []

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

        def request_full_status(self):
            self.requests += 1
            return self.connected

    monkeypatch.setattr(state, "PrinterMqttSession", FakeSession)
    return FakeSession
