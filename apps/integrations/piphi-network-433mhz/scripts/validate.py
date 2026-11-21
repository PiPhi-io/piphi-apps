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
assert f'INTEGRATION_VERSION = "{version}"' in (
    ROOT / "src" / "piphi_network_433mhz" / "app.py"
).read_text(encoding="utf-8")
expected_image = f"ghcr.io/piphi-io/piphi-network-433mhz:{version}"
assert manifest["image"] == expected_image
assert manifest["runtime"]["linux"]["container"]["image"] == expected_image
assert app["ci"]["enforcement"] == "full"
assert app["ci"]["build_container"] is True
assert {
    "pdm install --check",
    "pdm run pytest --cov=piphi_network_433mhz --cov-branch --cov-fail-under=80",
    "pdm run ruff check src tests",
    "pdm run ruff format --check src tests",
    "pdm run mypy src/piphi_network_433mhz",
    "pdm run bandit -q -r src",
    "pdm run python scripts/validate.py",
} <= set(app["ci"]["commands"])
assert manifest["requires"]["services"][0]["recommended_version"] == "0.2.1"
assert manifest["marketplace"]["quality_tier"] == "unrated"
assert manifest["marketplace"]["governance"]["qualification"]["status"] == "unverified"
assert not any(item.get("status") == "implemented" for item in manifest["security"]["event_mappings"])
assert {item["id"] for item in catalog["capabilities"] if item["status"] == "implemented"}

print("piphi-network-433mhz release contract is consistent")
