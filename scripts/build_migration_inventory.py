#!/usr/bin/env python3
"""Build a deterministic PiPhi Apps migration inventory from registry.json."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY = (
    "https://raw.githubusercontent.com/"
    "PiPhi-io/piphi-nework-registry/main/registry.json"
)

SELECTED_PATH_IMPORTS = {
    "https://github.com/PiPhi-io/piphi_network_widget_sdk": {
        "io.piphi.whole-home-energy": {
            "source_path": "pilot-packages/whole-home-energy",
            "destination": "apps/widgets/whole-home-energy",
        },
        "io.piphi.home-health": {
            "source_path": "pilot-packages/home-health",
            "destination": "apps/widgets/home-health",
        },
    }
}


def load_registry(source: str) -> list[dict[str, Any]]:
    if source.startswith(("https://", "http://")):
        with urllib.request.urlopen(source, timeout=30) as response:  # noqa: S310
            value = json.load(response)
    else:
        value = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("registry must contain a JSON array")
    return value


def repository_slug(repo_url: str) -> str:
    slug = repo_url.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.git$", "", slug, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")


def destination(repo_url: str, entries: list[dict[str, Any]]) -> str:
    types = {str(entry.get("type", "integration")) for entry in entries}
    slug = repository_slug(repo_url)
    if types == {"widget"}:
        return f"apps/widgets/{slug}"
    if types == {"platform_service"}:
        return f"apps/services/{slug}"
    return f"apps/integrations/{slug}"


def build_inventory(entries: list[dict[str, Any]], source: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        repo_url = entry.get("repo_url")
        if not isinstance(repo_url, str) or not repo_url:
            raise ValueError(f"registry entry {entry.get('id')!r} has no repo_url")
        grouped[repo_url].append(entry)

    repositories = []
    for repo_url, repo_entries in sorted(grouped.items()):
        selected_paths = SELECTED_PATH_IMPORTS.get(repo_url)
        import_plan: dict[str, Any]
        if selected_paths:
            import_plan = {
                "mode": "selected_paths",
                "targets": [
                    selected_paths[str(entry["id"])]
                    for entry in sorted(repo_entries, key=lambda item: str(item.get("id")))
                ],
            }
        else:
            import_plan = {
                "mode": "repository",
                "destination": destination(repo_url, repo_entries),
            }
        repositories.append(
            {
                "source_url": repo_url,
                "import": import_plan,
                "status": "pending",
                "entries": [
                    {
                        "id": entry.get("id"),
                        "type": entry.get("type"),
                        "version": entry.get("version"),
                        "ref": entry.get("ref"),
                        "manifest_path": entry.get("manifest_path"),
                    }
                    for entry in sorted(repo_entries, key=lambda item: str(item.get("id")))
                ],
            }
        )

    return {
        "schema_version": 1,
        "generated_from": source,
        "summary": {
            "entries": len(entries),
            "repositories": len(repositories),
            "integrations": sum(entry.get("type") == "integration" for entry in entries),
            "platform_services": sum(
                entry.get("type") == "platform_service" for entry in entries
            ),
            "widgets": sum(entry.get("type") == "widget" for entry in entries),
        },
        "repositories": repositories,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--output", default="migration/inventory.json")
    args = parser.parse_args()

    inventory = build_inventory(load_registry(args.registry), args.registry)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
