#!/usr/bin/env python3
"""Run trusted, metadata-declared CI commands for one app."""

from __future__ import annotations

import argparse
from pathlib import Path

from app_tooling import ROOT, load_app, run_commands, validate_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("app_path")
    args = parser.parse_args()
    path = (ROOT / args.app_path).resolve()
    if ROOT not in path.parents:
        raise ValueError("app path escapes repository")
    validate_app(path)
    app = load_app(path)
    if app["ci"]["enforcement"] == "legacy-static":
        print(f"{args.app_path}: legacy-static metadata validation only")
        return
    run_commands(path, app["ci"]["commands"])


if __name__ == "__main__":
    main()
