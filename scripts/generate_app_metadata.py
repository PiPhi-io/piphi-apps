#!/usr/bin/env python3
"""Generate initial per-app metadata from the migration inventory and registry."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from app_tooling import ROOT


def load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def detect_languages(path: Path) -> list[str]:
    languages = []
    checks = (
        ("pyproject.toml", "python"),
        ("package.json", "node"),
        ("go.mod", "go"),
        ("Cargo.toml", "rust"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("build.gradle.kts", "kotlin"),
        ("Gemfile", "ruby"),
        ("composer.json", "php"),
    )
    for filename, language in checks:
        if (path / filename).exists() and language not in languages:
            languages.append(language)
    if list(path.glob("*.csproj")):
        languages.append("dotnet")
    return languages or ["declarative"]


def toolchains(path: Path, languages: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    if "python" in languages:
        versions["python"] = "3.12"
    if "node" in languages:
        package = json.loads((path / "package.json").read_text(encoding="utf-8"))
        engine = str(package.get("engines", {}).get("node", "22"))
        match = re.search(r"\d+", engine)
        versions["node"] = match.group(0) if match else "22"
    if "go" in languages:
        match = re.search(r"^go\s+(\d+(?:\.\d+)?)", (path / "go.mod").read_text(), re.MULTILINE)
        versions["go"] = match.group(1) if match else "stable"
    defaults = {
        "rust": "stable",
        "java": "21",
        "kotlin": "21",
        "dotnet": "8.0.x",
        "ruby": "3.3",
        "php": "8.3",
    }
    for language, version in defaults.items():
        if language in languages:
            versions[language] = version
    return versions


def dockerfile(path: Path) -> str | None:
    for name in ("Dockerfile", "dockerfile"):
        if (path / name).is_file():
            return name
    return None


def commands(path: Path, languages: list[str]) -> list[str]:
    result: list[str] = []
    if "python" in languages and (path / "pdm.lock").is_file():
        result.extend(["pdm install --check"])
        if (path / "tests").is_dir() or (path / "test").is_dir():
            result.append("pdm run pytest")
    if "node" in languages and (path / "package.json").is_file():
        package = json.loads((path / "package.json").read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        result.append("npm ci")
        result.append("npm audit --omit=dev --audit-level=high")
        for script in ("check", "test", "validate", "build"):
            if script in scripts:
                result.append(f"npm run {script}")
    if "go" in languages:
        result.extend(["go test ./...", "go vet ./..."])
    if "rust" in languages:
        result.extend(["cargo test --locked", "cargo clippy --locked -- -D warnings"])
    return list(dict.fromkeys(result))


def image_target(image: str) -> tuple[str, str]:
    value = image.split("@", 1)[0]
    tail = value.rsplit("/", 1)[-1]
    if ":" in tail:
        value = value.rsplit(":", 1)[0]
    if value.startswith("ghcr.io/"):
        return "ghcr.io", value.removeprefix("ghcr.io/")
    if value.startswith("docker.io/"):
        return "docker.io", value.removeprefix("docker.io/")
    if "." in value.split("/", 1)[0] or ":" in value.split("/", 1)[0]:
        registry, repository = value.split("/", 1)
        return registry, repository
    return "docker.io", value


def adjusted_entries(repository: dict[str, Any]) -> list[tuple[Path, dict[str, Any]]]:
    plan = repository["import"]
    if plan["mode"] == "repository":
        root = ROOT / plan["destination"]
        return [(root, {**entry, "manifest": entry["manifest_path"]}) for entry in repository["entries"]]

    result = []
    entries = repository["entries"]
    for target in plan["targets"]:
        source = Path(target["source_path"])
        matches = [entry for entry in entries if Path(entry["manifest_path"]).is_relative_to(source)]
        if len(matches) != 1:
            raise ValueError(f"selected path {source} does not map to one entry")
        entry = matches[0]
        result.append(
            (
                ROOT / target["destination"],
                {**entry, "manifest": Path(entry["manifest_path"]).relative_to(source).as_posix()},
            )
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", default="migration/inventory.json")
    parser.add_argument("--registry", required=True)
    args = parser.parse_args()
    inventory = load(args.inventory)
    registry = {entry["id"]: entry for entry in load(args.registry)}

    grouped: dict[Path, dict[str, Any]] = {}
    for repository in inventory["repositories"]:
        for app_path, entry in adjusted_entries(repository):
            grouped.setdefault(
                app_path,
                {
                    "schema_version": 1,
                    "$schema": "../../../contracts/piphi-app.schema.json",
                    "slug": app_path.name,
                    "source": {"imported_from": repository["source_url"]},
                    "languages": detect_languages(app_path),
                    "toolchains": toolchains(app_path, detect_languages(app_path)),
                    "ci": {
                        "enforcement": "legacy-static",
                        "commands": commands(app_path, detect_languages(app_path)),
                        "build_container": False,
                    },
                    "packages": [],
                },
            )
            listing = registry[entry["id"]]
            manifest = json.loads((app_path / entry["manifest"]).read_text(encoding="utf-8"))
            package: dict[str, Any] = {
                "id": entry["id"],
                "type": entry["type"],
                "version": manifest.get("version", entry["version"]),
                "manifest": entry["manifest"],
                "release": {
                    "tag": "apps/{package_id}/v{version}",
                    "commands": [],
                },
            }
            if entry["type"] == "widget":
                package["artifact"] = {"kind": "widget", "output": "dist"}
            else:
                dockerfile_name = dockerfile(app_path)
                if dockerfile_name:
                    package["artifact"] = {
                        "kind": "oci",
                        "context": ".",
                        "dockerfile": dockerfile_name,
                        "platforms": ["linux/amd64", "linux/arm64"],
                    }
                    image = listing.get("image") or f"ghcr.io/piphi-io/{app_path.name}"
                    registry_host, image_repository = image_target(image)
                    package["publishing"] = {
                        "mode": "piphi_managed",
                        "environment": f"release-{registry_host.replace('.', '-')}",
                        "primary": {
                            "registry": registry_host,
                            "repository": image_repository,
                        },
                        "mirrors": [],
                    }
                else:
                    package["artifact"] = {"kind": "binary", "output": "dist"}
            grouped[app_path]["packages"].append(package)

    for path, metadata in grouped.items():
        (path / "piphi-app.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
    print(f"generated metadata for {len(grouped)} app directories")


if __name__ == "__main__":
    main()
