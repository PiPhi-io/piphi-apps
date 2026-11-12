#!/usr/bin/env python3
"""Emit a GitHub Actions matrix for apps affected by a diff."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app_tooling import ROOT, changed_app_directories, load_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--github-output")
    args = parser.parse_args()

    include = []
    for path in changed_app_directories(args.base, args.head):
        app = load_app(path)
        if app["ci"]["enforcement"] != "full":
            continue
        languages = set(app["languages"])
        toolchains = app["toolchains"]
        oci_artifacts = [
            package["artifact"]
            for package in app["packages"]
            if package["artifact"]["kind"] == "oci"
        ]
        oci = oci_artifacts[0] if oci_artifacts else {}
        include.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "slug": app["slug"],
                "python": "python" in languages,
                "node": "node" in languages,
                "go": "go" in languages,
                "rust": "rust" in languages,
                "java": bool({"java", "kotlin"} & languages),
                "dotnet": "dotnet" in languages,
                "ruby": "ruby" in languages,
                "php": "php" in languages,
                "build_container": bool(app["ci"]["build_container"]),
                "dockerfile": oci.get("dockerfile", "Dockerfile"),
                "context": oci.get("context", "."),
                "python_version": toolchains.get("python", "3.12"),
                "node_version": toolchains.get("node", "22"),
                "go_version": toolchains.get("go", "stable"),
                "java_version": toolchains.get("java", toolchains.get("kotlin", "21")),
                "dotnet_version": toolchains.get("dotnet", "8.0.x"),
                "ruby_version": toolchains.get("ruby", "3.3"),
                "php_version": toolchains.get("php", "8.3"),
            }
        )
    matrix = json.dumps({"include": include}, separators=(",", ":"))
    output_name = args.github_output or os.environ.get("GITHUB_OUTPUT")
    if output_name:
        with Path(output_name).open("a", encoding="utf-8") as handle:
            handle.write(f"matrix={matrix}\n")
            handle.write(f"has_apps={str(bool(include)).lower()}\n")
    else:
        print(matrix)


if __name__ == "__main__":
    main()
