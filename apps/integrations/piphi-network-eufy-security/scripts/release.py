#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Self

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
PYPROJECT_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")$')
PACKAGE_VERSION_RE = re.compile(r'(?m)^\s*"version"\s*:\s*"([^"]+)"')
DEFAULT_PREID = "alpha"
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
PREID_CHOICES = ("alpha", "beta", "rc")


@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> Self:
        match = SEMVER_RE.match(str(value).strip())
        if match is None:
            raise ValueError(f"Invalid semantic version: {value}")
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)), prerelease, build)

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value = f"{value}-" + ".".join(self.prerelease)
        if self.build:
            value = f"{value}+" + ".".join(self.build)
        return value

    def without_prerelease(self) -> Self:
        return SemVer(self.major, self.minor, self.patch, (), self.build)

    def with_prerelease(self, *parts: str) -> Self:
        return SemVer(self.major, self.minor, self.patch, tuple(parts), self.build)

    def stable_key(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def compare(self, other: Self) -> int:
        if self.stable_key() != other.stable_key():
            return -1 if self.stable_key() < other.stable_key() else 1
        if not self.prerelease and not other.prerelease:
            return 0
        if not self.prerelease:
            return 1
        if not other.prerelease:
            return -1
        return _compare_identifiers(self.prerelease, other.prerelease)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bump PiPhi runtime release metadata.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bump", choices=BUMP_CHOICES, help="Increment the current version.")
    mode.add_argument("--set-version", help="Set an explicit semantic version.")
    parser.add_argument("--preid", choices=PREID_CHOICES, default=DEFAULT_PREID)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--manifest", default="manifest.json")
    parser.add_argument("--pyproject", default="pyproject.toml")
    parser.add_argument("--package-json", default="package.json")
    parser.add_argument("--docker-image", default=None)
    parser.add_argument("--no-pin-container-image", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def resolve_repo_root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path(__file__).resolve().parents[1]


def resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else repo_root / path).resolve()


def read_version_file(path: Path) -> tuple[str, SemVer] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    if path.name == "pyproject.toml":
        match = PYPROJECT_VERSION_RE.search(text)
        if match is None:
            raise ValueError("Unable to find project version in pyproject.toml")
        return text, SemVer.parse(match.group(2))
    if path.name == "package.json":
        payload = json.loads(text)
        return text, SemVer.parse(str(payload.get("version") or ""))
    return None


def write_version_file(path: Path, text: str, version: str) -> None:
    if path.name == "pyproject.toml":
        updated, count = PYPROJECT_VERSION_RE.subn(rf'\g<1>{version}\g<3>', text, count=1)
        if count != 1:
            raise ValueError("Unable to update project version in pyproject.toml")
        path.write_text(updated, encoding="utf-8")
        return
    if path.name == "package.json":
        payload = json.loads(text)
        payload["version"] = version
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def resolve_target_version(current: SemVer, *, bump: str | None, set_version: str | None, preid: str) -> SemVer:
    if set_version is not None:
        target = SemVer.parse(set_version.strip())
        if target.compare(current) <= 0:
            raise ValueError(f"Explicit version must be newer than the current version ({current})")
        return target
    if bump is None:
        raise ValueError("Either --bump or --set-version is required")
    return bump_version(current, bump=bump, preid=preid)


def bump_version(current: SemVer, *, bump: str, preid: str) -> SemVer:
    stable = current.without_prerelease()
    if bump == "major":
        return SemVer(stable.major + 1, 0, 0)
    if bump == "minor":
        return SemVer(stable.major, stable.minor + 1, 0)
    if bump == "patch":
        return SemVer(stable.major, stable.minor, stable.patch + 1)
    if bump == "premajor":
        return SemVer(stable.major + 1, 0, 0).with_prerelease(preid, "1")
    if bump == "preminor":
        return SemVer(stable.major, stable.minor + 1, 0).with_prerelease(preid, "1")
    if bump == "prepatch":
        return SemVer(stable.major, stable.minor, stable.patch + 1).with_prerelease(preid, "1")
    if bump == "prerelease":
        return bump_prerelease(current, preid=preid)
    if bump == "release":
        if not current.prerelease:
            raise ValueError("Cannot promote a stable version. Use patch/minor/major or --set-version instead.")
        return current.without_prerelease()
    raise ValueError(f"Unsupported bump type: {bump}")


def bump_prerelease(current: SemVer, *, preid: str) -> SemVer:
    if not current.prerelease:
        return SemVer(current.major, current.minor, current.patch + 1).with_prerelease(preid, "1")
    stable = current.without_prerelease()
    if current.prerelease[0] != preid:
        return stable.with_prerelease(preid, "1")
    suffix = list(current.prerelease[1:])
    if not suffix:
        return stable.with_prerelease(preid, "1")
    if suffix[-1].isdigit():
        suffix[-1] = str(int(suffix[-1]) + 1)
    else:
        suffix.append("1")
    return stable.with_prerelease(preid, *suffix)


def _compare_identifiers(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    for left_part, right_part in zip(left, right):
        if left_part == right_part:
            continue
        left_numeric = left_part.isdigit()
        right_numeric = right_part.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_part) < int(right_part) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_part < right_part else 1
    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


def image_repository(image: str) -> str:
    image = image.strip()
    if "@" in image:
        image = image.split("@", 1)[0]
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    if last_colon > last_slash:
        return image[:last_colon]
    return image


def infer_primary_container_repo(manifest: dict) -> str | None:
    top_level_image = manifest.get("image")
    if isinstance(top_level_image, str) and top_level_image.strip():
        return image_repository(top_level_image)
    repos: set[str] = set()
    runtime = manifest.get("runtime")
    if isinstance(runtime, dict):
        for platform_config in runtime.values():
            if not isinstance(platform_config, dict):
                continue
            container = platform_config.get("container")
            if not isinstance(container, dict):
                continue
            image = container.get("image")
            if isinstance(image, str) and image.strip():
                repos.add(image_repository(image))
    if not repos:
        return None
    if len(repos) > 1:
        raise ValueError("Multiple runtime container image repositories found; pass --docker-image explicitly.")
    return next(iter(repos))


def update_primary_container_images(manifest: dict, *, docker_image: str, version: str) -> None:
    tagged_image = f"{docker_image}:{version}"
    if isinstance(manifest.get("image"), str) and image_repository(manifest["image"]) == docker_image:
        manifest["image"] = tagged_image
    runtime = manifest.get("runtime")
    if not isinstance(runtime, dict):
        return
    for platform_config in runtime.values():
        if not isinstance(platform_config, dict):
            continue
        container = platform_config.get("container")
        if not isinstance(container, dict):
            continue
        image = container.get("image")
        if isinstance(image, str) and image.strip() and image_repository(image) == docker_image:
            container["image"] = tagged_image


def main() -> int:
    args = parse_args()
    repo_root = resolve_repo_root(args.repo_root)
    manifest_path = resolve_path(repo_root, args.manifest)
    pyproject_path = resolve_path(repo_root, args.pyproject)
    package_path = resolve_path(repo_root, args.package_json)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_version = SemVer.parse(str(manifest.get("version") or "").strip())
    version_files = [
        (path, result)
        for path, result in [
            (pyproject_path, read_version_file(pyproject_path)),
            (package_path, read_version_file(package_path)),
        ]
        if result is not None
    ]
    for path, (_text, version) in version_files:
        if version.compare(manifest_version) != 0:
            raise ValueError(f"Version mismatch: {path.name}={version} manifest.json={manifest_version}")

    target = resolve_target_version(manifest_version, bump=args.bump, set_version=args.set_version, preid=args.preid)
    target_version = str(target)

    if args.dry_run:
        print(target_version)
        return 0

    manifest["version"] = target_version
    if not args.no_pin_container_image:
        docker_image = args.docker_image or infer_primary_container_repo(manifest)
        if docker_image:
            update_primary_container_images(manifest, docker_image=docker_image, version=target_version)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for path, (text, _version) in version_files:
        write_version_file(path, text, target_version)
    print(target_version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"release.py failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
