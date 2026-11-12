from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_REPOSITORY = "ghcr.io/piphi-io/piphi-network-reolink"
TAG_PATTERN = re.compile(
    r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$"
)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_release.py v<version>")

    release_ref = sys.argv[1].strip()
    if TAG_PATTERN.fullmatch(release_ref) is None:
        raise SystemExit(f"invalid release tag: {release_ref}")

    version = release_ref.removeprefix("v")
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    expected_image = f"{IMAGE_REPOSITORY}:{version}"
    runtime_image = (
        manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("image")
    )
    actual = {
        "manifest.json version": manifest.get("version"),
        "pyproject.toml version": project.get("version"),
        "manifest.json image": manifest.get("image"),
        "runtime container image": runtime_image,
    }
    expected = {
        "manifest.json version": version,
        "pyproject.toml version": version,
        "manifest.json image": expected_image,
        "runtime container image": expected_image,
    }
    errors = [
        f"{label}: expected {expected[label]!r}, got {value!r}"
        for label, value in actual.items()
        if value != expected[label]
    ]
    if errors:
        raise SystemExit("Release metadata mismatch:\n" + "\n".join(errors))

    print(f"Release metadata is synchronized for {release_ref}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

