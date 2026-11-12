from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
SETTINGS_PATH = ROOT / "src" / "piphi_network_tuya" / "settings.py"
MANIFEST_PATH = ROOT / "src" / "manifest.json"
BEHAVIORS_PATH = ROOT / "src" / "behaviors.json"
DOCKERFILE_PATH = ROOT / "Dockerfile"

PYPROJECT_VERSION_RE = re.compile(r'(?m)^version\s*=\s*"([^"]+)"$')
SETTINGS_VERSION_RE = re.compile(r'(?m)^INTEGRATION_VERSION\s*=\s*"([^"]+)"$')

errors: list[str] = []

pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
behaviors = json.loads(BEHAVIORS_PATH.read_text(encoding="utf-8"))
dockerfile_text = (
    DOCKERFILE_PATH.read_text(encoding="utf-8") if DOCKERFILE_PATH.exists() else ""
)

pyproject_match = PYPROJECT_VERSION_RE.search(pyproject_text)
settings_match = SETTINGS_VERSION_RE.search(settings_text)

if pyproject_match is None:
    errors.append("Unable to read [project].version from pyproject.toml")
if settings_match is None:
    errors.append("Unable to read INTEGRATION_VERSION from settings.py")

pyproject_version = pyproject_match.group(1) if pyproject_match else None
settings_version = settings_match.group(1) if settings_match else None
manifest_version = manifest.get("version")

if pyproject_version and settings_version and pyproject_version != settings_version:
    errors.append(
        f"Version mismatch: pyproject.toml={pyproject_version} settings.py={settings_version}"
    )
if pyproject_version and manifest_version and pyproject_version != manifest_version:
    errors.append(
        f"Version mismatch: pyproject.toml={pyproject_version} src/manifest.json={manifest_version}"
    )

api_endpoints = manifest.get("api", {}).get("endpoints", {})
if api_endpoints.get("manifest") != "/manifest.json":
    errors.append("manifest.api.endpoints.manifest must equal /manifest.json")
if api_endpoints.get("behaviors") != "/behaviors.json":
    errors.append("manifest.api.endpoints.behaviors must equal /behaviors.json")
if api_endpoints.get("manifest_static") != "/manifest.static.json":
    errors.append(
        "manifest.api.endpoints.manifest_static must equal /manifest.static.json"
    )
if api_endpoints.get("behaviors_static") != "/behaviors.static.json":
    errors.append(
        "manifest.api.endpoints.behaviors_static must equal /behaviors.static.json"
    )

required = manifest.get("api", {}).get("required", [])
for key in ["health", "entities", "command", "config", "ui_config"]:
    if key not in required:
        errors.append(f"manifest.api.required is missing {key}")

if manifest.get("metadata", {}).get("vendor_library") != "tinytuya":
    errors.append("manifest.metadata.vendor_library must equal tinytuya")

behavior_ids = {
    device.get("id")
    for device in behaviors.get("devices", [])
    if isinstance(device, dict)
}
for expected_id in {
    "tuya_plug",
    "tuya_light",
    "tuya_fan",
    "tuya_cover",
    "tuya_climate",
    "tuya_humidifier",
    "tuya_air_purifier",
}:
    if expected_id not in behavior_ids:
        errors.append(f"behaviors.json is missing device profile {expected_id}")

if dockerfile_text and "EXPOSE 4191" not in dockerfile_text:
    errors.append("Dockerfile must expose port 4191")
if dockerfile_text and "HEALTHCHECK" not in dockerfile_text:
    errors.append("Dockerfile must define a HEALTHCHECK")
if dockerfile_text and "USER piphi" not in dockerfile_text:
    errors.append("Dockerfile must run as non-root user piphi")
if (
    dockerfile_text
    and 'CMD ["python", "-m", "piphi_network_tuya.main"]' not in dockerfile_text
):
    errors.append("Dockerfile must start via python -m piphi_network_tuya.main")

if errors:
    raise SystemExit("\n".join(errors))

print("PiPhi Tuya validation passed.")
