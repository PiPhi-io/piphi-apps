#!/usr/bin/env python3
"""Validate migration inventory and any registry sources imported so far."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "migration" / "inventory.json"
EXPECTED_COUNTS = {
    "entries": 66,
    "repositories": 63,
    "integrations": 45,
    "platform_services": 11,
    "widgets": 10,
}
MAX_FILE_SIZE = 50 * 1024 * 1024


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid JSON file {path.relative_to(ROOT)}: {error}") from error


def validate_manifest(path: Path, entry_id: str) -> None:
    if not path.is_file():
        raise ValueError(f"imported entry {entry_id} is missing {path.relative_to(ROOT)}")
    value = read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"manifest for {entry_id} must contain a JSON object")


def validate_repository_import(repository: dict[str, Any]) -> int:
    plan = repository["import"]
    entries = repository["entries"]
    if plan["mode"] == "repository":
        destination = ROOT / plan["destination"]
        if not destination.exists():
            return 0
        for entry in entries:
            validate_manifest(destination / entry["manifest_path"], entry["id"])
        return len(entries)

    if plan["mode"] != "selected_paths":
        raise ValueError(f"unknown import mode for {repository['source_url']}")

    validated = 0
    for target in plan["targets"]:
        source_path = Path(target["source_path"])
        destination = ROOT / target["destination"]
        if not destination.exists():
            continue
        matching = [
            entry
            for entry in entries
            if Path(entry["manifest_path"]).is_relative_to(source_path)
        ]
        if len(matching) != 1:
            raise ValueError(f"selected import {source_path} must map to exactly one entry")
        entry = matching[0]
        relative_manifest = Path(entry["manifest_path"]).relative_to(source_path)
        validate_manifest(destination / relative_manifest, entry["id"])
        validated += 1
    return validated


def validate_files() -> None:
    apps = ROOT / "apps"
    if not apps.exists():
        return
    for path in apps.rglob("*"):
        if path.name == ".git" and path.is_dir():
            raise ValueError(f"nested Git repository found at {path.relative_to(ROOT)}")
        if path.is_file() and path.stat().st_size > MAX_FILE_SIZE:
            raise ValueError(f"file exceeds 50 MiB: {path.relative_to(ROOT)}")


def main() -> None:
    inventory = read_json(INVENTORY_PATH)
    if inventory.get("schema_version") != 1:
        raise ValueError("unsupported migration inventory schema")
    if inventory.get("summary") != EXPECTED_COUNTS:
        raise ValueError("migration inventory counts do not match the registry baseline")

    repositories = inventory.get("repositories")
    if not isinstance(repositories, list) or len(repositories) != EXPECTED_COUNTS["repositories"]:
        raise ValueError("migration inventory repository list is incomplete")

    source_urls = [repository["source_url"] for repository in repositories]
    if len(source_urls) != len(set(source_urls)):
        raise ValueError("migration inventory contains duplicate source repositories")

    imported_entries = sum(validate_repository_import(repository) for repository in repositories)
    validate_files()
    print(
        f"validated inventory for {EXPECTED_COUNTS['entries']} entries; "
        f"{imported_entries} imported manifests are present"
    )


if __name__ == "__main__":
    main()
