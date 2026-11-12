#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
PYPROJECT_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")$')
BUMP_CHOICES = (
    "major",
    "minor",
    "patch",
    "premajor",
    "preminor",
    "prepatch",
    "prerelease",
    "release",
)


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = SEMVER_RE.fullmatch(value.strip())
        if match is None:
            raise ValueError(f"Invalid semantic version: {value}")
        return cls(
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            tuple(match.group(4).split(".")) if match.group(4) else (),
            tuple(match.group(5).split(".")) if match.group(5) else (),
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def precedence(self) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
        identifiers = tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in self.prerelease
        )
        return self.major, self.minor, self.patch, int(not self.prerelease), identifiers

    def stable(self) -> "SemVer":
        return SemVer(self.major, self.minor, self.patch)


def bump_version(current: SemVer, bump: str, preid: str) -> SemVer:
    stable = current.stable()
    if bump == "major":
        return SemVer(stable.major + 1, 0, 0)
    if bump == "minor":
        return SemVer(stable.major, stable.minor + 1, 0)
    if bump == "patch":
        return SemVer(stable.major, stable.minor, stable.patch + 1)
    if bump == "premajor":
        return SemVer(stable.major + 1, 0, 0, (preid, "1"))
    if bump == "preminor":
        return SemVer(stable.major, stable.minor + 1, 0, (preid, "1"))
    if bump == "prepatch":
        return SemVer(stable.major, stable.minor, stable.patch + 1, (preid, "1"))
    if bump == "release":
        if not current.prerelease:
            raise ValueError("Cannot promote a stable version")
        return stable
    if bump != "prerelease":
        raise ValueError(f"Unsupported bump type: {bump}")
    if not current.prerelease:
        return SemVer(current.major, current.minor, current.patch + 1, (preid, "1"))
    if current.prerelease[0] != preid:
        return SemVer(current.major, current.minor, current.patch, (preid, "1"))
    suffix = list(current.prerelease[1:])
    if suffix and suffix[-1].isdigit():
        suffix[-1] = str(int(suffix[-1]) + 1)
    else:
        suffix.append("1")
    return SemVer(current.major, current.minor, current.patch, (preid, *suffix))


def image_repository(image: str) -> str:
    image = image.split("@", 1)[0]
    slash = image.rfind("/")
    colon = image.rfind(":")
    return image[:colon] if colon > slash else image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update Tesla EV release metadata.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bump", choices=BUMP_CHOICES)
    mode.add_argument("--set-version")
    parser.add_argument("--preid", choices=("alpha", "beta", "rc"), default="alpha")
    parser.add_argument("--docker-image", default="piphinetwork/tesla-ev")
    parser.add_argument("--repo-root")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    pyproject_path = root / "pyproject.toml"
    manifest_path = root / "src" / "manifest.json"
    pyproject = pyproject_path.read_text(encoding="utf-8")
    match = PYPROJECT_VERSION_RE.search(pyproject)
    if match is None:
        raise ValueError("Unable to find project version in pyproject.toml")

    current = SemVer.parse(match.group(2))
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    manifest_version = SemVer.parse(str(manifest.get("version", "")))
    if current.precedence() != manifest_version.precedence():
        raise ValueError(
            f"Version mismatch: pyproject.toml={current} manifest.json={manifest_version}"
        )

    target = SemVer.parse(args.set_version) if args.set_version else bump_version(current, args.bump, args.preid)
    if target.precedence() <= current.precedence():
        raise ValueError(f"Release version must be newer than {current}")
    version = str(target)
    if args.dry_run:
        print(version)
        return 0

    container = manifest.get("runtime", {}).get("linux", {}).get("container", {})
    image = container.get("image")
    if not isinstance(image, str) or image_repository(image) != args.docker_image:
        raise ValueError("Manifest container image does not match --docker-image")

    pyproject = PYPROJECT_VERSION_RE.sub(rf"\g<1>{version}\g<3>", pyproject, count=1)
    old_manifest_version = f'"version": "{current}"'
    old_manifest_image = f'"image": "{image}"'
    if old_manifest_version not in manifest_text or old_manifest_image not in manifest_text:
        raise ValueError("Unable to locate release metadata in manifest.json")
    manifest_text = manifest_text.replace(
        old_manifest_version, f'"version": "{version}"', 1
    ).replace(
        old_manifest_image, f'"image": "{args.docker_image}:{version}"', 1
    )

    pyproject_path.write_text(pyproject, encoding="utf-8")
    manifest_path.write_text(manifest_text, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"release.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
