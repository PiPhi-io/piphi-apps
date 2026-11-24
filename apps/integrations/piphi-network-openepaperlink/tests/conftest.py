from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from piphi_network_openepaperlink import state


@pytest.fixture(autouse=True)
def isolate_runtime_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("PIPHI_STATE_SNAPSHOT_PATH", str(tmp_path / "openepaperlink-state.json"))
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
    state.persisted_state.clear()
    state.refresh_locks.clear()
    state.runtime.process_state.current_generation = None
    monkeypatch.setattr(state, "event_scheduler", lambda **_kwargs: _CompletedTask())
    yield
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.registry.recent_events.clear()
    state.persisted_state.clear()
    state.refresh_locks.clear()
    state.runtime.process_state.current_generation = None


class _CompletedTask:
    def add_done_callback(self, callback) -> None:
        return None
