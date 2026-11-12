#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = ROOT / "pyproject.toml"
SETTINGS_PATH = ROOT / "src" / "piphi_network_tuya" / "settings.py"
MANIFEST_PATH = ROOT / "src" / "manifest.json"
EXPERIENCE_PATH = ROOT / "experiences" / "devices" / "package.source.json"

PYPROJECT_VERSION_RE = re.compile(r'(?m)^(version\s*=\s*")([^"]+)(")$')
SETTINGS_VERSION_RE = re.compile(r'(?m)^(INTEGRATION_VERSION\s*=\s*")([^"]+)(")$')
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
DEFAULT_PREID = "alpha"
BUMP_CHOICES = [
    "major",
    "minor",
    "patch",
    "premajor",
    "preminor",
    "prepatch",
    "prerelease",
    "release",
]
PREID_CHOICES = ["alpha", "beta", "rc"]


@dataclass(frozen=True, slots=True)
class SemVer:
    major: int
    minor: int
    patch: int
    prerelease: tuple[str, ...] = ()
    build: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "SemVer":
        match = SEMVER_RE.match(value.strip())
        if match is None:
            raise ValueError(f"Invalid semantic version: {value}")
        prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
        build = tuple(match.group(5).split(".")) if match.group(5) else ()
        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)),
            prerelease=prerelease,
            build=build,
        )

    def __str__(self) -> str:
        value = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            value += "-" + ".".join(self.prerelease)
        if self.build:
            value += "+" + ".".join(self.build)
        return value

    def without_prerelease(self) -> "SemVer":
        return SemVer(self.major, self.minor, self.patch, (), self.build)

    def with_prerelease(self, *parts: str) -> "SemVer":
        return SemVer(self.major, self.minor, self.patch, tuple(parts), self.build)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bump PiPhi Tuya runtime metadata versions."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--set-version",
        help="Set an explicit semantic version, for example 0.1.1 or 0.1.1-alpha.1",
    )
    mode.add_argument(
        "--bump", choices=BUMP_CHOICES, help="Increment the semantic version"
    )
    parser.add_argument(
        "--preid",
        choices=PREID_CHOICES,
        default=DEFAULT_PREID,
        help="Prerelease identifier for pre* bumps",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the next version without writing files",
    )
    return parser.parse_args()


def replace_single(
    pattern: re.Pattern[str], text: str, replacement: str, *, label: str
) -> str:
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ValueError(f"Unable to update {label}")
    return updated


def bump_prerelease(current: SemVer, *, preid: str) -> SemVer:
    if not current.prerelease:
        return SemVer(current.major, current.minor, current.patch + 1).with_prerelease(
            preid, "1"
        )

    stable = current.without_prerelease()
    current_preid = current.prerelease[0]
    if current_preid != preid:
        return stable.with_prerelease(preid, "1")

    suffix = list(current.prerelease[1:])
    if not suffix:
        return stable.with_prerelease(preid, "1")

    last_token = suffix[-1]
    if last_token.isdigit():
        suffix[-1] = str(int(last_token) + 1)
    else:
        suffix.append("1")
    return stable.with_prerelease(preid, *suffix)


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
        return SemVer(stable.major, stable.minor, stable.patch + 1).with_prerelease(
            preid, "1"
        )
    if bump == "prerelease":
        return bump_prerelease(current, preid=preid)
    if bump == "release":
        if not current.prerelease:
            raise ValueError("Cannot promote a stable version with --bump release")
        return current.without_prerelease()
    raise ValueError(f"Unsupported bump type: {bump}")


def main() -> None:
    args = parse_args()
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    settings_text = SETTINGS_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    experience = json.loads(EXPERIENCE_PATH.read_text(encoding="utf-8"))

    current_match = PYPROJECT_VERSION_RE.search(pyproject_text)
    if current_match is None:
        raise SystemExit("Unable to find version in pyproject.toml")
    current_version = SemVer.parse(current_match.group(2))

    next_version = (
        SemVer.parse(args.set_version.strip())
        if args.set_version
        else bump_version(current_version, bump=args.bump, preid=args.preid)
    )
    next_version_str = str(next_version)

    if args.dry_run:
        print(next_version_str)
        return

    pyproject_text = replace_single(
        PYPROJECT_VERSION_RE,
        pyproject_text,
        rf"\g<1>{next_version_str}\g<3>",
        label="pyproject version",
    )
    settings_text = replace_single(
        SETTINGS_VERSION_RE,
        settings_text,
        rf"\g<1>{next_version_str}\g<3>",
        label="settings version",
    )
    manifest["version"] = next_version_str
    manifest["image"] = f"docker.io/piphinetwork/piphi-network-tuya:{next_version_str}"
    runtime_linux = manifest.get("runtime", {}).get("linux", {})
    container = (
        runtime_linux.get("container", {}) if isinstance(runtime_linux, dict) else {}
    )
    if isinstance(container, dict):
        container["image"] = (
            f"docker.io/piphinetwork/piphi-network-tuya:{next_version_str}"
        )
    identity = experience.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("version"), str):
        raise ValueError("Experience package identity.version is missing")
    identity["version"] = next_version_str

    PYPROJECT_PATH.write_text(pyproject_text, encoding="utf-8")
    SETTINGS_PATH.write_text(settings_text, encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    EXPERIENCE_PATH.write_text(
        json.dumps(experience, indent=2) + "\n", encoding="utf-8"
    )

    print(next_version_str)


if __name__ == "__main__":
    main()
