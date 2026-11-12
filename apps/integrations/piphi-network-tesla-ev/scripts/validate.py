from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "src" / "manifest.json").read_text(encoding="utf-8"))
behaviors = json.loads((ROOT / "src" / "behaviors.json").read_text(encoding="utf-8"))

required = {"health", "entities", "command", "config", "ui_config"}
missing = required - set(manifest.get("api", {}).get("endpoints", {}))
if missing:
    raise SystemExit(f"manifest missing endpoints: {sorted(missing)}")
if not behaviors.get("devices"):
    raise SystemExit("behaviors.json must declare at least one device")
if manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("ports", [{}])[0].get("container") != 3090:
    raise SystemExit("manifest container port must remain 3090")

print("Tesla runtime contract files are valid")
