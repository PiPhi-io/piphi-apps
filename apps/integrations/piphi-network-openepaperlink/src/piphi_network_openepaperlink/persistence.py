from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

STATE_SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = "/var/lib/piphi/openepaperlink-state.json"


def state_path() -> Path:
    return Path(os.getenv("PIPHI_STATE_SNAPSHOT_PATH", DEFAULT_STATE_PATH))


def load_state(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = path or state_path()
    try:
        payload = json.loads(source.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Persisted OpenEPaperLink state is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise ValueError("Persisted OpenEPaperLink state has an unsupported schema")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        raise TypeError("Persisted OpenEPaperLink state has invalid entries")
    entries: dict[str, dict[str, Any]] = {}
    for config_id, raw in raw_entries.items():
        if not isinstance(config_id, str) or not isinstance(raw, dict):
            raise TypeError("Persisted OpenEPaperLink state has an invalid record")
        tag_ids = raw.get("tag_ids", [])
        last_good = raw.get("last_good", {})
        if not isinstance(tag_ids, list) or not all(isinstance(item, str) for item in tag_ids):
            raise ValueError("Persisted OpenEPaperLink state has invalid tag identities")
        if not isinstance(last_good, dict):
            raise TypeError("Persisted OpenEPaperLink state has invalid last-good data")
        entries[config_id] = {
            "device_id": str(raw.get("device_id") or ""),
            "tag_ids": sorted(set(tag_ids)),
            "last_good": dict(last_good),
            "inventory_initialized": bool(raw.get("inventory_initialized")),
            "status": str(raw.get("status") or "initializing"),
            "consecutive_failures": max(0, int(raw.get("consecutive_failures") or 0)),
        }
    return entries


def save_state(entries: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    destination = path or state_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "entries": entries,
    }
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, sort_keys=True, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
