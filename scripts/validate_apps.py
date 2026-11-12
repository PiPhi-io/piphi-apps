#!/usr/bin/env python3
from app_tooling import validate_all_apps


if __name__ == "__main__":
    apps, packages = validate_all_apps()
    print(f"validated {packages} packages across {apps} app directories")
