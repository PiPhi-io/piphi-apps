from __future__ import annotations

import json
from pathlib import Path

from piphi_webrtc_sidecar.contract import ENDPOINTS, REQUIRED_ENDPOINTS

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "manifest.json").read_text())
dockerfile = (ROOT / "Dockerfile").read_text()
errors: list[str] = []

if manifest.get("$schema") != "./schema/piphi-manifest.schema.json":
    errors.append("manifest must reference ./schema/piphi-manifest.schema.json")
if not (ROOT / "schema" / "piphi-manifest.schema.json").exists():
    errors.append("schema/piphi-manifest.schema.json is missing")
if manifest.get("kind") != "platform_service":
    errors.append("kind must be platform_service")
if manifest.get("deployment_mode") != "sidecar":
    errors.append("deployment_mode must be sidecar")
if manifest.get("onboarding") != {"mode": "service"}:
    errors.append("onboarding must use zero-setup service mode")

for forbidden in ("config", "identity", "entities", "commands"):
    if forbidden in manifest:
        errors.append(f"managed service manifest must not define {forbidden}")
if manifest.get("capabilities") != {}:
    errors.append("managed service capabilities must be empty")

provided = manifest.get("provides", {}).get("services", [])
if provided != [
    {
        "id": "piphi.service.webrtc-sidecar",
        "kind": "platform_service",
        "capabilities": ["camera.media.v1"],
        "shared": True,
    }
]:
    errors.append("manifest must provide the shared camera.media.v1 service")

required = manifest.get("api", {}).get("required", [])
endpoints = manifest.get("api", {}).get("endpoints", {})
if required != REQUIRED_ENDPOINTS:
    errors.append("api.required does not match the runtime service contract")
for key, endpoint in ENDPOINTS.items():
    if endpoints.get(key) != endpoint:
        errors.append(f"api.endpoints.{key} does not match the runtime contract")

port = (
    manifest.get("runtime", {})
    .get("linux", {})
    .get("container", {})
    .get("ports", [{}])[0]
    .get("container")
)
if not isinstance(port, int):
    errors.append("runtime.linux.container.ports[0].container must be an integer")
elif f"EXPOSE {port}" not in dockerfile:
    errors.append(f"Dockerfile must expose manifest port {port}")

if errors:
    raise SystemExit("\n".join(errors))

print("PiPhi managed camera media service validation passed.")
