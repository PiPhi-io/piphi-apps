from __future__ import annotations

import json
from pathlib import Path

from piphi_network_kaiterra_api.contract import CAPABILITIES, COMMANDS, ENDPOINTS, REQUIRED_ENDPOINTS
from piphi_network_kaiterra_api.settings import INTEGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "src" / "manifest.json").read_text())
app_metadata = json.loads((ROOT / "piphi-app.json").read_text())
catalog = json.loads((ROOT / "capability-catalog.json").read_text())
behaviors = json.loads((ROOT / "src" / "behaviors.json").read_text())
dockerfile = (ROOT / "Dockerfile").read_text() if (ROOT / "Dockerfile").exists() else ""
errors: list[str] = []

if manifest.get("$schema") != "./schema/piphi-manifest.schema.json":
    errors.append("manifest must reference ./schema/piphi-manifest.schema.json")
if not (ROOT / "schema" / "piphi-manifest.schema.json").exists():
    errors.append("schema/piphi-manifest.schema.json is missing")

for key in REQUIRED_ENDPOINTS:
    if key not in manifest.get("api", {}).get("required", []):
        errors.append(f"api.required is missing {key}")
    endpoint = manifest.get("api", {}).get("endpoints", {}).get(key)
    if not isinstance(endpoint, str) or not endpoint.startswith("/"):
        errors.append(f"api.endpoints.{key} must be an absolute path")
    if ENDPOINTS.get(key) != endpoint:
        errors.append(f"contract endpoint {key} does not match manifest")

port = manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("ports", [{}])[0].get("container")
if not isinstance(port, int):
    errors.append("runtime.linux.container.ports[0].container must be an integer")
elif dockerfile and f"EXPOSE {port}" not in dockerfile:
    errors.append(f"Dockerfile must expose manifest port {port}")

for capability_id, capability in manifest.get("capabilities", {}).items():
    if capability.get("kind") == "action" and capability_id not in COMMANDS:
        errors.append(f"action capability {capability_id} must map to a command")

if set(manifest.get("capabilities", {})) != set(CAPABILITIES):
    errors.append("manifest capabilities do not match runtime contract")
if set(manifest.get("commands", {})) != set(COMMANDS):
    errors.append("manifest commands do not match runtime contract")
if set(behaviors["devices"][0]["capabilities"]) != set(CAPABILITIES):
    errors.append("behavior capabilities do not match runtime contract")
versions = {
    INTEGRATION_VERSION,
    str(manifest.get("version")),
    str(app_metadata["packages"][0]["version"]),
}
if len(versions) != 1:
    errors.append(f"version mismatch: {sorted(versions)}")
implemented_actions = {
    action
    for entry in catalog.get("entries", []) if entry.get("status") == "implemented"
    for action in entry.get("actions", [])
}
if implemented_actions != set(COMMANDS):
    errors.append("catalog implemented actions do not match runtime commands")

if errors:
    raise SystemExit("\n".join(errors))

print("PiPhi scaffold validation passed.")
