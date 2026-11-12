"""Validate a release tag against the checked-out runtime and image metadata."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_release(tag: str, root: Path = ROOT) -> list[str]:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        return ["Release tag must be vMAJOR.MINOR.PATCH (for example v0.1.0)"]
    version = tag[1:]
    manifest = json.loads((root / "manifest.json").read_text())
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    settings = ast.parse((root / "src/piphi_network_sense/settings.py").read_text())
    runtime_version = next(
        (ast.literal_eval(node.value) for node in settings.body
         if isinstance(node, ast.Assign)
         and any(isinstance(target, ast.Name) and target.id == "INTEGRATION_VERSION"
                 for target in node.targets)),
        None,
    )
    errors = []
    for name, value in {
        "manifest.version": manifest.get("version"),
        "project.version": project.get("version"),
        "INTEGRATION_VERSION": runtime_version,
    }.items():
        if value != version:
            errors.append(f"{name} must match release tag {tag}; got {value!r}")
    expected_image = f"piphinetwork/piphi-network-sense:{version}"
    if manifest.get("image") != expected_image:
        errors.append(f"manifest.image must be {expected_image}")
    if manifest["runtime"]["linux"]["container"].get("image") != expected_image:
        errors.append(f"runtime container image must be {expected_image}")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_release.py vMAJOR.MINOR.PATCH")
    errors = validate_release(sys.argv[1])
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Sense release metadata matches {sys.argv[1]}.")
