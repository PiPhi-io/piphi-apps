#!/usr/bin/env python3
"""Create a reviewable registry cutover proposal from release evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app_tooling import ROOT, find_package, release_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--digest", required=True)
    parser.add_argument("--output", default="registry-proposal.json")
    args = parser.parse_args()

    path, _app, package = find_package(args.package)
    plan = release_plan(args.package, args.version)
    repository = os.environ.get("GITHUB_REPOSITORY", "PiPhi-io/piphi-apps")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    proposal = {
        "schema_version": 1,
        "id": args.package,
        "version": args.version,
        "repo_name": "piphi-apps",
        "repo_url": f"{server}/{repository}",
        "manifest_path": (path.relative_to(ROOT) / package["manifest"]).as_posix(),
        "ref": plan["tag"],
    }
    if plan["artifact_kind"] == "oci":
        proposal["image"] = f"{plan['image']}:{args.version}"
        proposal["digest"] = args.digest
    else:
        proposal["artifact"] = {
            "release_asset": f"{args.package}-{args.version}.tgz",
            "integrity": args.digest,
        }
    Path(args.output).write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
