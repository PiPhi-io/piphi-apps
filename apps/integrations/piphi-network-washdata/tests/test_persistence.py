from __future__ import annotations

import sqlite3

import pytest

from piphi_network_washdata.persistence import CycleState, CycleStore


def _state(cursor: str | None = None) -> CycleState:
    return CycleState(
        config_id="config-1",
        binding_id="binding-1",
        binding_key="appliance_power",
        canonical_device_id="device-1",
        next_cursor=cursor,
    )


def test_migrates_v1_database_and_rehydrates_state(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY);
        INSERT INTO schema_migrations VALUES (1);
        CREATE TABLE cycle_states (config_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, next_cursor TEXT, payload TEXT NOT NULL);
        CREATE TABLE processed_events (config_id TEXT NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY(config_id,event_id), FOREIGN KEY(config_id) REFERENCES cycle_states(config_id) ON DELETE CASCADE);
    """)
    connection.close()

    store = CycleStore(path)
    state = _state("cursor-1")
    state.cycle_state = "running"
    store.commit_page(state, ["event-1"], "cursor-1")

    restarted = CycleStore(path)
    loaded = restarted.load("config-1")
    assert restarted.schema_version() == 2
    assert loaded is not None and loaded.cycle_state == "running"
    assert loaded.next_cursor == "cursor-1"
    assert restarted.processed("config-1", "event-1")


def test_page_state_event_ids_and_cursor_rollback_together(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    store = CycleStore(path)
    store.save(_state("cursor-1"))

    def fail() -> None:
        raise RuntimeError("injected crash")

    crashing = CycleStore(path, before_commit=fail)
    changed = _state("cursor-2")
    changed.cycle_state = "running"
    with pytest.raises(RuntimeError, match="injected crash"):
        crashing.commit_page(changed, ["event-2"], "cursor-2")

    loaded = CycleStore(path).load("config-1")
    assert loaded is not None and loaded.next_cursor == "cursor-1"
    assert loaded.cycle_state == "idle"
    assert not store.processed("config-1", "event-2")
