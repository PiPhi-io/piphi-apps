from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_PATH = "/var/lib/piphi/passive-ble/state.json"


def state_path() -> Path:
    return Path(os.getenv("PIPHI_BLE_MONITOR_STATE_PATH", DEFAULT_PATH))


def load_state(path: Path | None = None) -> dict[str, dict[str, Any]]:
    source = path or state_path()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("persisted BLE monitor state is unreadable") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("persisted BLE monitor state has an unsupported schema")
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("persisted BLE monitor entries are invalid")
    result: dict[str, dict[str, Any]] = {}
    for config_id, value in entries.items():
        if not isinstance(config_id, str) or not isinstance(value, dict):
            raise ValueError("persisted BLE monitor entry is invalid")
        public_state = value.get("state", {})
        if not isinstance(public_state, dict):
            raise ValueError("persisted BLE monitor public state is invalid")
        # This allow-list prevents future config or credential fields from being
        # persisted accidentally.
        result[config_id] = {
            "device_id": str(value.get("device_id") or ""),
            "state": {
                str(key): item
                for key, item in public_state.items()
                if key in {
                    "receiver_healthy", "observation_fresh", "sensor_available",
                    "measurement_age_seconds", "temperature_c", "humidity_percent",
                    "battery_percent", "rssi_dbm", "last_measurement_at",
                }
            },
        }
    return result


def save_state(entries: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    destination = path or state_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    allowed = {
        "receiver_healthy", "observation_fresh", "sensor_available",
        "measurement_age_seconds", "temperature_c", "humidity_percent",
        "battery_percent", "rssi_dbm", "last_measurement_at",
    }
    safe_entries = {
        str(config_id): {
            "device_id": str(value.get("device_id") or ""),
            "state": {
                str(key): item
                for key, item in dict(value.get("state") or {}).items()
                if key in allowed
            },
        }
        for config_id, value in entries.items()
        if isinstance(value, dict)
    }
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(
                {"schema_version": SCHEMA_VERSION, "entries": safe_entries},
                temporary, sort_keys=True, separators=(",", ":"),
            )
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
