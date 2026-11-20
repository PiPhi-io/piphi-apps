from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(message)


if len(sys.argv) != 2:
    fail("usage: check_release.py apps/piphi-network-tapo-cameras/v<version>")

tag = sys.argv[1]
prefix = "apps/piphi-network-tapo-cameras/v"
if not tag.startswith(prefix):
    fail(f"release tag must start with {prefix}")
version = tag.removeprefix(prefix)

pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
manifest = json.loads((ROOT / "manifest.json").read_text())
app = json.loads((ROOT / "piphi-app.json").read_text())
experience = json.loads((ROOT / "experiences/status/package.source.json").read_text())
settings = (ROOT / "src/piphi_network_tapo_cameras/settings.py").read_text()
dockerfile = (ROOT / "Dockerfile").read_text()

checks = {
    "pyproject.toml": pyproject["project"]["version"],
    "manifest.json": manifest["version"],
    "piphi-app.json": app["packages"][0]["version"],
    "experience package": experience["identity"]["version"],
}
for source, actual in checks.items():
    if actual != version:
        fail(f"{source} has version {actual!r}; expected {version!r}")

expected_image = f"ghcr.io/piphi-io/piphi-network-tapo-cameras:{version}"
for source, actual in {
    "manifest image": manifest["image"],
    "manifest container image": manifest["runtime"]["linux"]["container"]["image"],
}.items():
    if actual != expected_image:
        fail(f"{source} is {actual!r}; expected {expected_image!r}")

settings_match = re.search(r'^INTEGRATION_VERSION = "([^"]+)"$', settings, re.MULTILINE)
if settings_match is None or settings_match.group(1) != version:
    fail("settings.py integration version does not match the release")
if f"ARG RELEASE_VERSION={version}" not in dockerfile:
    fail("Dockerfile release version does not match the release")

print(f"Release metadata is consistent for {tag}.")
