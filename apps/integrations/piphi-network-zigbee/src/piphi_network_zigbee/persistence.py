from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def state_path() -> Path:
    return Path(os.getenv("PIPHI_ZIGBEE_STATE_PATH", "/var/lib/piphi/zigbee/configs.json"))


def save_entries(entries: dict[str, dict[str, Any]]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def load_entries() -> dict[str, dict[str, Any]]:
    path = state_path()
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Persisted Zigbee configuration must be an object.")
    return {
        str(config_id): entry
        for config_id, entry in payload.items()
        if isinstance(entry, dict) and str(config_id).strip()
    }
