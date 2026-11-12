#!/usr/bin/env python3
from __future__ import annotations

import argparse

from app_tooling import run_release_commands


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    run_release_commands(args.package, args.version)
