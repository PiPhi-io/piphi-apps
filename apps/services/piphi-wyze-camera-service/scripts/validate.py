from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from piphi_wyze_camera_service.contract import ENDPOINTS, REQUIRED_ENDPOINTS

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / "manifest.json").read_text())
schema = json.loads((ROOT / "schema" / "piphi-manifest.schema.json").read_text())
dockerfile = (ROOT / "Dockerfile").read_text() if (ROOT / "Dockerfile").exists() else ""
errors: list[str] = []

try:
    jsonschema.Draft202012Validator(schema).validate(manifest)
except jsonschema.ValidationError as exc:
    errors.append(f"manifest schema validation failed: {exc.message}")

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

port = (
    manifest.get("runtime", {})
    .get("linux", {})
    .get("container", {})
    .get("ports", [{}])[0]
    .get("container")
)
if not isinstance(port, int):
    errors.append("runtime.linux.container.ports[0].container must be an integer")
elif dockerfile and f"EXPOSE {port}" not in dockerfile:
    errors.append(f"Dockerfile must expose manifest port {port}")

provided_services = manifest.get("provides", {}).get("services", [])
if not any(
    "camera.bridge.wyze.v1" in service.get("capabilities", [])
    for service in provided_services
    if isinstance(service, dict)
):
    errors.append("manifest must provide camera.bridge.wyze.v1")

if errors:
    raise SystemExit("\n".join(errors))

print("PiPhi scaffold validation passed.")
