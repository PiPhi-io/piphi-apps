#!/usr/bin/env python3
"""Shared discovery, validation, CI, and release planning for PiPhi apps."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
APPS_ROOT = ROOT / "apps"
METADATA_NAME = "piphi-app.json"
SUPPORTED_LANGUAGES = {
    "python",
    "node",
    "go",
    "rust",
    "java",
    "kotlin",
    "dotnet",
    "ruby",
    "php",
    "oci",
    "declarative",
}
PACKAGE_TYPES = {"integration", "platform_service", "widget"}
ARTIFACT_KINDS = {"oci", "widget", "binary"}
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")


class AppMetadataError(ValueError):
    """Raised when app metadata is unsafe or internally inconsistent."""


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AppMetadataError(f"invalid JSON file {path.relative_to(ROOT)}: {error}") from error


def app_directories() -> list[Path]:
    return sorted(path for path in APPS_ROOT.glob("*/*") if path.is_dir())


def load_app(path: Path) -> dict[str, Any]:
    metadata_path = path / METADATA_NAME
    value = read_json(metadata_path)
    if not isinstance(value, dict):
        raise AppMetadataError(f"{metadata_path.relative_to(ROOT)} must contain an object")
    return value


def _require_string(value: Any, field: str, app_path: Path) -> str:
    if not isinstance(value, str) or not value:
        raise AppMetadataError(f"{app_path.relative_to(ROOT)}: {field} must be a string")
    return value


def _validate_publish_target(target: Any, field: str, app_path: Path) -> None:
    if not isinstance(target, dict):
        raise AppMetadataError(f"{app_path.relative_to(ROOT)}: {field} must be an object")
    registry = _require_string(target.get("registry"), f"{field}.registry", app_path)
    repository = _require_string(target.get("repository"), f"{field}.repository", app_path)
    if ":" in repository or "@" in repository:
        raise AppMetadataError(
            f"{app_path.relative_to(ROOT)}: {field}.repository must not contain a tag or digest"
        )
    if "/" not in repository:
        raise AppMetadataError(
            f"{app_path.relative_to(ROOT)}: {field}.repository must include a namespace"
        )
    if "/" in registry or registry.startswith(("http://", "https://")):
        raise AppMetadataError(
            f"{app_path.relative_to(ROOT)}: {field}.registry must be a registry host"
        )


def _manifest_image(manifest: dict[str, Any]) -> str | None:
    if isinstance(manifest.get("image"), str):
        return manifest["image"]
    container = manifest.get("container")
    if isinstance(container, dict) and isinstance(container.get("image"), str):
        return container["image"]
    runtime = manifest.get("runtime")
    if isinstance(runtime, dict):
        for platform in runtime.values():
            if not isinstance(platform, dict):
                continue
            container = platform.get("container")
            if isinstance(container, dict) and isinstance(container.get("image"), str):
                return container["image"]
    return None


def validate_app(path: Path, package_ids: set[str] | None = None) -> int:
    data = load_app(path)
    relative = path.relative_to(ROOT)
    if data.get("schema_version") != 1:
        raise AppMetadataError(f"{relative}: unsupported schema_version")
    slug = _require_string(data.get("slug"), "slug", path)
    if slug != path.name:
        raise AppMetadataError(f"{relative}: slug must match directory name {path.name!r}")

    languages = data.get("languages")
    if not isinstance(languages, list) or not languages or not all(
        isinstance(language, str) and language for language in languages
    ):
        raise AppMetadataError(f"{relative}: languages must be a non-empty string array")
    unknown = set(languages) - SUPPORTED_LANGUAGES
    toolchains = data.get("toolchains")
    if not isinstance(toolchains, dict) or not all(
        isinstance(language, str)
        and isinstance(version, str)
        and version
        for language, version in toolchains.items()
    ):
        raise AppMetadataError(f"{relative}: toolchains must map languages to versions")
    missing_toolchains = {
        language for language in languages if language not in {"oci", "declarative"}
    } - set(toolchains)
    if missing_toolchains:
        raise AppMetadataError(f"{relative}: missing toolchains for {sorted(missing_toolchains)}")

    ci = data.get("ci")
    if not isinstance(ci, dict) or ci.get("enforcement") not in {"legacy-static", "full"}:
        raise AppMetadataError(f"{relative}: ci.enforcement must be legacy-static or full")
    commands = ci.get("commands")
    if not isinstance(commands, list) or not all(isinstance(command, str) and command for command in commands):
        raise AppMetadataError(f"{relative}: ci.commands must be a string array")
    if not isinstance(ci.get("build_container"), bool):
        raise AppMetadataError(f"{relative}: ci.build_container must be boolean")

    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise AppMetadataError(f"{relative}: packages must be a non-empty array")
    local_ids: set[str] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise AppMetadataError(f"{relative}: package entries must be objects")
        package_id = _require_string(package.get("id"), "packages[].id", path)
        if package_id in local_ids or package_ids is not None and package_id in package_ids:
            raise AppMetadataError(f"duplicate package id {package_id!r}")
        local_ids.add(package_id)
        package_type = package.get("type")
        if package_type not in PACKAGE_TYPES:
            raise AppMetadataError(f"{relative}: unsupported package type {package_type!r}")
        version = _require_string(package.get("version"), "packages[].version", path)
        if not SEMVER.fullmatch(version):
            raise AppMetadataError(f"{relative}: invalid semantic version {version!r}")
        manifest_path = path / _require_string(package.get("manifest"), "packages[].manifest", path)
        if not manifest_path.is_file():
            raise AppMetadataError(f"{relative}: missing manifest {manifest_path.relative_to(path)}")
        manifest = read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise AppMetadataError(f"{relative}: manifest must contain an object")
        if manifest.get("id") not in {None, package_id}:
            raise AppMetadataError(f"{relative}: package id does not match manifest id")
        if manifest.get("version") not in {None, version}:
            raise AppMetadataError(f"{relative}: package version does not match manifest version")

        artifact = package.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("kind") not in ARTIFACT_KINDS:
            raise AppMetadataError(f"{relative}: package artifact kind is invalid")
        if artifact["kind"] == "oci":
            dockerfile = path / _require_string(
                artifact.get("dockerfile"), "packages[].artifact.dockerfile", path
            )
            if not dockerfile.is_file():
                raise AppMetadataError(f"{relative}: OCI package is missing {dockerfile.name}")
            publishing = package.get("publishing")
            if not isinstance(publishing, dict) or publishing.get("mode") not in {
                "piphi_managed",
                "external",
            }:
                raise AppMetadataError(f"{relative}: OCI publishing mode is invalid")
            _validate_publish_target(publishing.get("primary"), "publishing.primary", path)
            if ci["enforcement"] == "full":
                primary = publishing["primary"]
                expected_image = f"{primary['registry']}/{primary['repository']}:{version}"
                manifest_image = _manifest_image(manifest)
                if manifest_image != expected_image:
                    raise AppMetadataError(
                        f"{relative}: manifest image {manifest_image!r} must match "
                        f"the release target {expected_image!r}"
                    )
            mirrors = publishing.get("mirrors", [])
            if not isinstance(mirrors, list):
                raise AppMetadataError(f"{relative}: publishing.mirrors must be an array")
            for index, target in enumerate(mirrors):
                _validate_publish_target(target, f"publishing.mirrors[{index}]", path)
                if target["registry"] not in {publishing["primary"]["registry"], "ghcr.io"}:
                    raise AppMetadataError(
                        f"{relative}: mirrors currently support the primary registry or ghcr.io"
                    )

        release = package.get("release")
        if not isinstance(release, dict) or release.get("tag") != "apps/{package_id}/v{version}":
            raise AppMetadataError(f"{relative}: release tag must use the namespaced template")
        release_commands = release.get("commands", [])
        if not isinstance(release_commands, list) or not all(
            isinstance(command, str) and command for command in release_commands
        ):
            raise AppMetadataError(f"{relative}: release.commands must be a string array")
        if ci["enforcement"] == "full" and artifact["kind"] != "oci" and not release_commands:
            raise AppMetadataError(
                f"{relative}: full non-OCI packages require release.commands"
            )

    if unknown and not any(package["artifact"]["kind"] == "oci" for package in packages):
        raise AppMetadataError(
            f"{relative}: unknown languages {sorted(unknown)} require a portable OCI artifact"
        )
    if package_ids is not None:
        package_ids.update(local_ids)
    return len(packages)


def validate_all_apps() -> tuple[int, int]:
    directories = app_directories()
    package_ids: set[str] = set()
    packages = sum(validate_app(path, package_ids) for path in directories)
    return len(directories), packages


def changed_app_directories(base: str, head: str = "HEAD") -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, head],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    changed = [Path(line) for line in result.stdout.splitlines() if line]
    global_change = any(
        path.parts and path.parts[0] in {"contracts", "scripts"}
        or path.as_posix().startswith(".github/workflows/")
        for path in changed
    )
    if global_change:
        return app_directories()
    selected: set[Path] = set()
    for path in changed:
        if len(path.parts) >= 3 and path.parts[0] == "apps":
            candidate = ROOT.joinpath(*path.parts[:3])
            if candidate.is_dir():
                selected.add(candidate)
    return sorted(selected)


def run_commands(app_path: Path, commands: Iterable[str]) -> None:
    for command in commands:
        print(f"[{app_path.relative_to(ROOT)}] $ {command}", flush=True)
        subprocess.run(
            ["bash", "-euo", "pipefail", "-c", command],
            cwd=app_path,
            check=True,
        )


def find_package(package_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    for path in app_directories():
        app = load_app(path)
        for package in app["packages"]:
            if package["id"] == package_id:
                return path, app, package
    raise AppMetadataError(f"unknown package id {package_id!r}")


def release_plan(package_id: str, version: str) -> dict[str, str]:
    path, app, package = find_package(package_id)
    if app["ci"]["enforcement"] != "full":
        raise AppMetadataError(
            f"{package_id} remains legacy-static; enable full CI before releasing from the monorepo"
        )
    if package["version"] != version:
        raise AppMetadataError(
            f"requested version {version} does not match metadata version {package['version']}"
        )
    artifact = package["artifact"]
    toolchains = app["toolchains"]
    plan = {
        "app_path": path.relative_to(ROOT).as_posix(),
        "slug": app["slug"],
        "package_id": package_id,
        "version": version,
        "artifact_kind": artifact["kind"],
        "tag": f"apps/{package_id}/v{version}",
        "prerelease": str("-" in version).lower(),
        "environment": package.get("publishing", {}).get("environment", "release"),
        "release_commands": json.dumps(package["release"].get("commands", [])),
        "output": artifact.get("output", "dist"),
        "manifest": package["manifest"],
    }
    languages = set(app["languages"])
    for language in ("python", "node", "go", "rust", "dotnet", "ruby", "php"):
        plan[language] = str(language in languages).lower()
    plan["java"] = str(bool({"java", "kotlin"} & languages)).lower()
    for language in ("python", "node", "go", "rust", "dotnet", "ruby", "php"):
        plan[f"{language}_version"] = toolchains.get(language, "")
    plan["java_version"] = toolchains.get("java", toolchains.get("kotlin", ""))
    if artifact["kind"] == "oci":
        publishing = package["publishing"]
        primary = publishing["primary"]
        plan.update(
            {
                "publishing_mode": publishing["mode"],
                "registry": primary["registry"],
                "repository": primary["repository"],
                "image": f"{primary['registry']}/{primary['repository']}",
                "dockerfile": artifact["dockerfile"],
                "context": artifact.get("context", "."),
                "platforms": ",".join(
                    artifact.get("platforms", ["linux/amd64", "linux/arm64"])
                ),
                "mirrors": json.dumps(publishing.get("mirrors", [])),
                "ghcr_required": str(
                    primary["registry"] == "ghcr.io"
                    or any(
                        mirror["registry"] == "ghcr.io"
                        for mirror in publishing.get("mirrors", [])
                    )
                ).lower(),
                "tags": ",".join(
                    [f"{primary['registry']}/{primary['repository']}:{version}"]
                    + [
                        f"{mirror['registry']}/{mirror['repository']}:{version}"
                        for mirror in publishing.get("mirrors", [])
                    ]
                ),
            }
        )
    return plan


def run_release_commands(package_id: str, version: str) -> None:
    path, _app, package = find_package(package_id)
    release_plan(package_id, version)
    run_commands(path, package["release"].get("commands", []))
