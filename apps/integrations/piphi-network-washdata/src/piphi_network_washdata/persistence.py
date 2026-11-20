from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2


@dataclass(slots=True)
class CycleState:
    config_id: str
    binding_id: str
    binding_key: str
    canonical_device_id: str
    next_cursor: str | None = None
    cycle_state: str = "idle"
    cycle_started_at: str | None = None
    cycle_finished_at: str | None = None
    cycle_duration_s: float | None = None
    power_w: float | None = None
    peak_power_w: float | None = None
    cycle_energy_kwh: float = 0.0
    lifetime_cycle_count: int = 0
    start_candidate_count: int = 0
    start_candidate_at: str | None = None
    stop_candidate_count: int = 0
    last_sample_at: str | None = None
    last_sample_power_w: float | None = None
    stale: bool = False
    detector_status: str = "healthy"
    source_error: str | None = None

    @property
    def cycle_active(self) -> bool:
        return self.cycle_state == "running"

    def public(self) -> dict[str, Any]:
        return {
            "connected": self.detector_status == "healthy",
            "available": self.detector_status not in {"unavailable", "binding_changed"},
            "stale": self.stale,
            "detector_status": self.detector_status,
            "cycle_state": self.cycle_state,
            "cycle_active": self.cycle_active,
            "cycle_started_at": self.cycle_started_at,
            "cycle_finished_at": self.cycle_finished_at,
            "cycle_duration_s": self.cycle_duration_s,
            "power_w": self.power_w,
            "peak_power_w": self.peak_power_w,
            "cycle_energy_kwh": self.cycle_energy_kwh,
            "lifetime_cycle_count": self.lifetime_cycle_count,
            "last_sample_at": self.last_sample_at,
        }


class CycleStore:
    def __init__(
        self, path: str | Path, *, before_commit: Callable[[], None] | None = None
    ) -> None:
        self.path = str(path)
        self.before_commit = before_commit
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _migrate(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            applied = {
                int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if 1 not in applied:
                connection.executescript("""
                    CREATE TABLE cycle_states (
                        config_id TEXT PRIMARY KEY,
                        binding_id TEXT NOT NULL,
                        next_cursor TEXT,
                        payload TEXT NOT NULL
                    );
                    CREATE TABLE processed_events (
                        config_id TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        PRIMARY KEY (config_id, event_id),
                        FOREIGN KEY (config_id) REFERENCES cycle_states(config_id) ON DELETE CASCADE
                    );
                    INSERT INTO schema_migrations(version) VALUES (1);
                """)
            if 2 not in applied:
                connection.execute(
                    "ALTER TABLE cycle_states ADD COLUMN binding_key TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "ALTER TABLE cycle_states ADD COLUMN canonical_device_id TEXT NOT NULL DEFAULT ''"
                )
                connection.execute("INSERT INTO schema_migrations(version) VALUES (2)")

    def schema_version(self) -> int:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)

    def load(self, config_id: str) -> CycleState | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM cycle_states WHERE config_id = ?", (config_id,)
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
        payload.update(
            config_id=config_id,
            binding_id=str(row["binding_id"]),
            binding_key=str(row["binding_key"]),
            canonical_device_id=str(row["canonical_device_id"]),
            next_cursor=row["next_cursor"],
        )
        return CycleState(**payload)

    def save(self, state: CycleState) -> None:
        self.commit_page(state, (), state.next_cursor)

    def commit_page(
        self, state: CycleState, event_ids: Iterable[str], next_cursor: str | None
    ) -> None:
        state.next_cursor = next_cursor
        payload = asdict(state)
        for key in ("config_id", "binding_id", "binding_key", "canonical_device_id", "next_cursor"):
            payload.pop(key)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO cycle_states(config_id, binding_id, next_cursor, payload, binding_key, canonical_device_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(config_id) DO UPDATE SET binding_id=excluded.binding_id,
                     next_cursor=excluded.next_cursor, payload=excluded.payload,
                     binding_key=excluded.binding_key, canonical_device_id=excluded.canonical_device_id""",
                (
                    state.config_id,
                    state.binding_id,
                    next_cursor,
                    json.dumps(payload, sort_keys=True),
                    state.binding_key,
                    state.canonical_device_id,
                ),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO processed_events(config_id, event_id) VALUES (?, ?)",
                ((state.config_id, event_id) for event_id in event_ids),
            )
            if self.before_commit is not None:
                self.before_commit()

    def processed(self, config_id: str, event_id: str) -> bool:
        return event_id in self.processed_ids(config_id, [event_id])

    def processed_ids(self, config_id: str, event_ids: Iterable[str]) -> set[str]:
        values = list(dict.fromkeys(event_ids))
        if not values:
            return set()
        placeholders = ",".join("?" for _ in values)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT event_id FROM processed_events WHERE config_id = ? AND event_id IN ({placeholders})",  # nosec B608
                (config_id, *values),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def delete(self, config_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM cycle_states WHERE config_id = ?", (config_id,))
