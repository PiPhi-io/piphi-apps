from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    manifest_path = Path(__file__).resolve().parents[2] / "manifest.json"
    return json.loads(manifest_path.read_text())
