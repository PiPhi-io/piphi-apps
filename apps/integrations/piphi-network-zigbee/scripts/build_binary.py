from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "scripts" / "binary_entry.py"
BASE_NAME = "piphi-network-zigbee"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a native executable with PyInstaller.")
    parser.add_argument("--clean", action="store_true", help="remove PyInstaller build directories before building")
    parser.add_argument("--name", default=default_binary_name(), help="output executable name")
    args = parser.parse_args()

    if args.clean:
        shutil.rmtree(ROOT / "build" / "pyinstaller", ignore_errors=True)
        shutil.rmtree(ROOT / "dist" / "binary", ignore_errors=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        args.name,
        "--distpath",
        str(ROOT / "dist" / "binary"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build" / "pyinstaller"),
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "httptools",
        "--collect-submodules",
        "watchfiles",
        "--collect-submodules",
        "websockets",
        "--hidden-import",
        "piphi_network_zigbee.main",
        str(ENTRYPOINT),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def default_binary_name() -> str:
    system = platform.system().lower() or "unknown"
    machine = normalize_machine(platform.machine())
    suffix = ".exe" if system == "windows" else ".bin"
    return f"{BASE_NAME}-{system}-{machine}{suffix}"


def normalize_machine(machine: str) -> str:
    normalized = machine.lower().replace("amd64", "x86_64")
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    return normalized or "unknown"


if __name__ == "__main__":
    main()
