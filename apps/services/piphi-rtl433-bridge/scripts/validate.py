from __future__ import annotations

import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


app = load_json(ROOT / "piphi-app.json")
manifest = load_json(ROOT / "src" / "manifest.json")
catalog = load_json(ROOT / "capability-catalog.json")
with (ROOT / "pyproject.toml").open("rb") as handle:
    project = tomllib.load(handle)["project"]

version = app["packages"][0]["version"]
assert version == manifest["version"] == project["version"] == catalog["release"]
expected_image = f"ghcr.io/piphi-io/rtl433-bridge:{version}"
assert manifest["image"] == expected_image
assert manifest["runtime"]["linux"]["container"]["image"] == expected_image
container = manifest["runtime"]["linux"]["container"]
assert container.get("privileged") is not True
assert container.get("network_mode") != "host"
assert container["read_only"] is True
assert container["cap_drop"] == ["ALL"]
assert "rtl433_command" not in manifest["config"]["schema"]["properties"]
assert "RTL433_COMMAND" not in (ROOT / "src" / "piphi_rtl433_bridge" / "config.py").read_text()
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
upstream = catalog["upstream"]
assert upstream["revision"] in dockerfile
assert upstream["archive_sha256"] in dockerfile
assert manifest["marketplace"]["quality_tier"] == "unrated"

print("piphi-rtl433-bridge release contract is consistent")
