#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PYPROJECT_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")$')
EXPERIENCE_VERSION_RE = re.compile(r'("identity"\s*:\s*\{.*?"version"\s*:\s*")[^"]+("\s*\})', re.DOTALL)


def parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"Invalid stable semantic version: {value}")
    return tuple(int(match.group(index)) for index in range(1, 4))


def format_version(value: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in value)


def bump_version(current: tuple[int, int, int], bump: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def update_manifest_image(manifest: dict, image: str, version: str) -> None:
    tagged_image = f"{image}:{version}"
    manifest["image"] = tagged_image
    runtime = manifest.get("runtime")
    linux = runtime.get("linux") if isinstance(runtime, dict) else None
    container = linux.get("container") if isinstance(linux, dict) else None
    if isinstance(container, dict):
        container["image"] = tagged_image


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bump", choices=("patch", "minor", "major"))
    mode.add_argument("--set-version")
    parser.add_argument("--docker-image", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    pyproject_path = root / "pyproject.toml"
    manifest_path = root / "src" / "manifest.json"
    experience_path = root / "experiences" / "environment" / "package.source.json"
    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    match = PYPROJECT_VERSION_RE.search(pyproject_text)
    if match is None:
        raise ValueError("Unable to find project version")

    current = parse_version(match.group(2))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if parse_version(str(manifest.get("version") or "")) != current:
        raise ValueError("pyproject.toml and manifest.json versions do not match")

    target = parse_version(args.set_version) if args.set_version else bump_version(current, args.bump)
    if target <= current:
        raise ValueError(f"Release version must be newer than {format_version(current)}")
    version = format_version(target)
    if args.dry_run:
        print(version)
        return 0

    updated = PYPROJECT_VERSION_RE.sub(rf"\g<1>{version}\g<3>", pyproject_text, count=1)
    manifest["version"] = version
    update_manifest_image(manifest, args.docker_image, version)
    pyproject_path.write_text(updated, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if experience_path.exists():
        experience_text = experience_path.read_text(encoding="utf-8")
        updated_experience, count = EXPERIENCE_VERSION_RE.subn(
            rf"\g<1>{version}\g<2>", experience_text, count=1
        )
        if count != 1:
            raise ValueError(f"Unable to update experience version in {experience_path}")
        experience_path.write_text(updated_experience, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"release.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
