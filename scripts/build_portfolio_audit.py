#!/usr/bin/env python3
"""Build the durable Home Assistant parity portfolio inventory."""

from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = (
    "https://raw.githubusercontent.com/"
    "PiPhi-io/piphi-nework-registry/main/registry.json"
)
DEFAULT_CONFIG = ROOT / "docs/home-assistant-parity/portfolio-config.json"
DEFAULT_OUTPUT = ROOT / "docs/home-assistant-parity/inventory.json"


class PortfolioAuditError(ValueError):
    """Raised when portfolio source, registry, and audit metadata disagree."""


def load_json(source: str | Path) -> Any:
    source_text = str(source)
    if source_text.startswith(("https://", "http://")):
        with urllib.request.urlopen(source_text, timeout=30) as response:  # noqa: S310
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


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


def immutable_image(image: str | None, digest: str | None) -> str | None:
    """Return a digest-pinned OCI reference without retaining a mutable tag."""
    if not image or not digest:
        return None
    if "@" in image:
        image = image.split("@", 1)[0]
    last_slash = image.rfind("/")
    last_colon = image.rfind(":")
    if last_colon > last_slash:
        image = image[:last_colon]
    return f"{image}@{digest}"


def local_tags(root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "tag", "--list", "apps/*"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def display_path(path: Path, root: Path = ROOT) -> Path:
    """Prefer a repository-relative display path without rejecting external output."""
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def discover_packages(apps_root: Path) -> dict[str, dict[str, Any]]:
    packages: dict[str, dict[str, Any]] = {}
    for metadata_path in sorted(apps_root.glob("*/*/piphi-app.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        app_path = metadata_path.parent
        for package in metadata.get("packages", []):
            package_id = package.get("id")
            if not isinstance(package_id, str) or not package_id:
                raise PortfolioAuditError(f"invalid package id in {metadata_path}")
            if package_id in packages:
                raise PortfolioAuditError(f"duplicate package id {package_id!r}")
            manifest_path = app_path / package["manifest"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            packages[package_id] = {
                "id": package_id,
                "type": package["type"],
                "folder": app_path.relative_to(apps_root.parent).as_posix(),
                "source_version": package["version"],
                "manifest_path": package["manifest"],
                "manifest_image": _manifest_image(manifest),
                "imported_from": metadata.get("source", {}).get("imported_from"),
                "ci_enforcement": metadata["ci"]["enforcement"],
                "ci_build_container": metadata["ci"]["build_container"],
                "ci_commands": metadata["ci"]["commands"],
                "artifact_kind": package["artifact"]["kind"],
                "platforms": package["artifact"].get("platforms", []),
                "publishing_mode": package.get("publishing", {}).get("mode"),
                "publishing_target": package.get("publishing", {}).get("primary"),
                "release_tag": package["release"]["tag"].format(
                    package_id=package_id, version=package["version"]
                ),
            }
    return packages


def build_inventory(
    packages: dict[str, dict[str, Any]],
    registry_entries: Iterable[dict[str, Any]],
    config: dict[str, Any],
    *,
    source_revision: str,
    registry_revision: str,
    tags: set[str],
) -> dict[str, Any]:
    registry = {entry["id"]: entry for entry in registry_entries}
    exclusions = config.get("exclusions", {})
    comparators = config.get("comparators", {})
    evidence = config.get("audit_evidence", {})
    portfolio_ledger = config.get("portfolio_ledger")
    verification_sets = config.get("release_verification_sets", {})
    verification_overrides = config.get("release_verification_overrides", {})
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []

    for package_id, package in sorted(packages.items()):
        entry = registry.get(package_id)
        if package["type"] == "widget":
            excluded.append({"id": package_id, "reason": "widget"})
            continue
        if package_id in exclusions:
            excluded.append({"id": package_id, "reason": exclusions[package_id]})
            continue
        if entry is None:
            raise PortfolioAuditError(f"source package {package_id!r} is absent from registry")
        if entry.get("owner") != "PiPhi-io":
            excluded.append({"id": package_id, "reason": "third-party or unowned"})
            continue
        if package_id not in comparators:
            raise PortfolioAuditError(f"in-scope package {package_id!r} has no HA comparator")

        marketplace = entry.get("marketplace", {})
        governance = marketplace.get("governance", {})
        qualification = governance.get("qualification", {})
        registry_image = entry.get("image")
        image_digest = entry.get("image_digest")
        expected_tag = package["release_tag"]
        release_verification: dict[str, Any] = {
            "platforms_verified": False,
            "oci_labels_verified": False,
            "sbom_verified": False,
            "provenance_verified": False,
            "attestations_verified": False,
            "non_root_verified": False,
        }
        for verification_set in verification_sets.values():
            if package_id in verification_set.get("packages", []):
                release_verification.update(
                    {
                        key: value
                        for key, value in verification_set.items()
                        if key != "packages"
                    }
                )
        release_verification.update(verification_overrides.get(package_id, {}))
        audit_evidence = list(evidence.get(package_id, []))
        if isinstance(portfolio_ledger, str) and portfolio_ledger:
            audit_evidence.append(portfolio_ledger)
        rows.append(
            {
                "id": package_id,
                "type": package["type"],
                "source": {
                    key: package[key]
                    for key in (
                        "folder",
                        "source_version",
                        "manifest_path",
                        "manifest_image",
                        "imported_from",
                        "ci_enforcement",
                        "ci_build_container",
                        "ci_commands",
                    )
                },
                "release": {
                    "artifact_kind": package["artifact_kind"],
                    "platforms": package["platforms"],
                    "publishing_mode": package["publishing_mode"],
                    "publishing_target": package["publishing_target"],
                    "expected_tag": expected_tag,
                    "tag_present_locally": expected_tag in tags,
                    "registry_ref": entry.get("ref"),
                    "registry_image": registry_image,
                    "image_digest": image_digest,
                    "immutable_image": immutable_image(registry_image, image_digest),
                    **release_verification,
                },
                "registry": {
                    "version": entry.get("version"),
                    "repo_url": entry.get("repo_url"),
                    "manifest_path": entry.get("manifest_path"),
                    "owner": entry.get("owner"),
                    "trust_level": entry.get("trust_level"),
                    "risk_level": entry.get("risk_level"),
                    "runtime_requirements": entry.get("runtime_requirements", []),
                    "quality_tier": marketplace.get("quality_tier", "unrated"),
                    "publication_status": governance.get("publication_status"),
                    "rollout_percent": governance.get("rollout_percent"),
                    "lifecycle_status": governance.get("lifecycle_status"),
                    "qualification_status": qualification.get("status"),
                },
                "consistency": {
                    "source_registry_version_match": (
                        package["source_version"] == entry.get("version")
                    ),
                    "source_registry_image_match": (
                        package["manifest_image"] == registry_image
                    ),
                    "immutable_registry_image": bool(image_digest),
                },
                "home_assistant": comparators[package_id],
                "audit": {
                    "status": "audited" if audit_evidence else "pending",
                    "evidence": audit_evidence,
                },
            }
        )

    configured = set(comparators)
    discovered = {row["id"] for row in rows}
    stale = sorted(configured - discovered)
    if stale:
        raise PortfolioAuditError(f"comparator config contains out-of-scope packages: {stale}")

    return {
        "schema_version": 1,
        "source_revision": source_revision,
        "registry_revision": registry_revision,
        "scope": {
            "in_scope": len(rows),
            "excluded": len(excluded),
            "audited": sum(row["audit"]["status"] == "audited" for row in rows),
            "pending": sum(row["audit"]["status"] == "pending" for row in rows),
        },
        "exclusions": excluded,
        "packages": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--registry-revision", required=True)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    registry_entries = load_json(args.registry)
    if not isinstance(registry_entries, list):
        raise PortfolioAuditError("registry must contain a JSON array")
    config = load_json(args.config)
    inventory = build_inventory(
        discover_packages(ROOT / "apps"),
        registry_entries,
        config,
        source_revision=git_revision(ROOT),
        registry_revision=args.registry_revision,
        tags=local_tags(ROOT),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {inventory['scope']['in_scope']} in-scope packages to "
        f"{display_path(output)}"
    )


if __name__ == "__main__":
    main()
