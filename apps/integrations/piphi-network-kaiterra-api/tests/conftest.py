from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-kaiterra-automation-actions-{os.getpid()}.sqlite3",
)
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


RUNTIME_HEADERS = {
    "X-Container-Id": "container-test",
    "X-PiPhi-Integration-Token": "token-test",
}


@pytest.fixture(autouse=True)
def reset_runtime_collections():
    from piphi_network_kaiterra_api import state

    state.runtime.auth.container_id = "container-test"
    state.runtime.auth.internal_token = "token-test"
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
    state.runtime_data.configs.clear()
    state.runtime_data.clients.clear()
    state.runtime_data.poll_tasks.clear()
    yield
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
