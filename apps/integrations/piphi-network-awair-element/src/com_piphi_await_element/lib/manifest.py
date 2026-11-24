import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    source_path = Path(__file__).parent.parent.parent / "manifest.json"
    packaged_path = Path(__file__).parent.parent / "manifest.json"
    manifest_path = source_path if source_path.exists() else packaged_path
    with manifest_path.open("r", encoding="utf-8") as manifest_file:
        return json.load(manifest_file)
