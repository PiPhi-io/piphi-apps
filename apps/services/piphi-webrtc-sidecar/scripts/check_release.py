from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tag = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
    raise SystemExit("release tag must use vMAJOR.MINOR.PATCH")

version = tag.removeprefix("v")
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
settings = (ROOT / "src/piphi_webrtc_sidecar/settings.py").read_text(encoding="utf-8")

expected_image = f"ghcr.io/piphi-io/piphi-webrtc-sidecar:{version}"
checks = {
    "manifest version": manifest.get("version") == version,
    "package version": project.get("project", {}).get("version") == version,
    "manifest image": manifest.get("image") == expected_image,
    "runtime image": manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("image")
    == expected_image,
    "container label version": f"ARG APP_VERSION={version}" in dockerfile,
    "runtime package version": f'INTEGRATION_VERSION = "{version}"' in settings,
}
failed = [label for label, passed in checks.items() if not passed]
if failed:
    raise SystemExit("release metadata mismatch: " + ", ".join(failed))
print(f"Release metadata matches {tag}.")
