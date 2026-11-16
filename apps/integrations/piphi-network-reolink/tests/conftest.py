from __future__ import annotations

import pytest

from piphi_network_reolink import state


@pytest.fixture(autouse=True)
def allow_test_runtime_auth(monkeypatch):
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")
    monkeypatch.setattr(state.runtime_data, "client_connector", state.ReolinkClient.connect)
