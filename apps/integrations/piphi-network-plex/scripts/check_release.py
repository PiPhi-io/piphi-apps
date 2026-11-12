"""Offline release consistency gate; does not publish or promote qualification."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

from registry_entry import build_entry

ROOT = Path(__file__).resolve().parents[1]


def validate_release(root: Path = ROOT, release_ref: str | None = None) -> None:
    manifest = json.loads((root / "manifest.json").read_text())
    entry = json.loads((root / "registry/plex.json").read_text())
    version = manifest["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must use major.minor.patch")
    if release_ref is not None and release_ref != f"v{version}":
        raise ValueError("Release ref must be the tag matching manifest.version")
    if entry != build_entry(manifest):
        raise ValueError("registry/plex.json does not match the manifest-derived entry")
    project = tomllib.loads((root / "pyproject.toml").read_text())
    if project["project"]["version"] != version:
        raise ValueError("Python package version differs from manifest.version")
    expected_image = f"docker.io/piphinetwork/piphi-network-plex:{version}"
    if manifest["image"] != expected_image or manifest["runtime"]["linux"]["container"]["image"] != expected_image:
        raise ValueError("Runtime image references do not match the release version")
    for slug in ("recently-added", "continue-watching", "library-search"):
        package = json.loads((root / f"widgets/{slug}/widget.manifest.json").read_text())
        bundled = (root / f"widgets/{slug}/dist/widget.js").read_bytes()
        digest = "sha384-" + base64.b64encode(hashlib.sha384(bundled).digest()).decode()
        catalog = next(item for item in manifest["ui"]["widget_packages"] if item["id"] == package["id"])
        if package["integrity"] != digest or catalog["integrity"] != digest:
            raise ValueError(f"Widget integrity mismatch: {slug}")
        if catalog["entry"] != f"/media/providers/plex/widgets/{slug}/widget.js":
            raise ValueError(f"Widget does not use the Core artifact route: {slug}")


if __name__ == "__main__":
    validate_release(release_ref=sys.argv[1] if len(sys.argv) > 1 else None)
    print("Release consistency checks passed")
