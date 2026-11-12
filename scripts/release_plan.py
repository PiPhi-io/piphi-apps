#!/usr/bin/env python3
"""Validate and emit one independent package release plan."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app_tooling import release_plan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--github-output")
    args = parser.parse_args()
    plan = release_plan(args.package, args.version)
    output_name = args.github_output or os.environ.get("GITHUB_OUTPUT")
    if output_name:
        with Path(output_name).open("a", encoding="utf-8") as handle:
            for key, value in plan.items():
                handle.write(f"{key}={value}\n")
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
