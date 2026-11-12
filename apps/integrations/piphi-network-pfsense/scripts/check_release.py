from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _json(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def _runtime_version() -> str:
    settings = (ROOT / "src/piphi_network_pfsense/settings.py").read_text()
    match = re.search(r'^INTEGRATION_VERSION\s*=\s*"([^"]+)"$', settings, re.MULTILINE)
    if match is None:
        raise SystemExit("Unable to find INTEGRATION_VERSION in settings.py")
    return match.group(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a pfSense release tag")
    parser.add_argument("tag", help="Release tag, for example v0.1.0")
    args = parser.parse_args()

    match = SEMVER.fullmatch(args.tag)
    if match is None:
        raise SystemExit(f"Release tag is not semantic versioning: {args.tag}")
    version = args.tag.removeprefix("v").split("+", 1)[0]
    manifest = _json("manifest.json")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    sources = {
        "manifest.json": manifest.get("version"),
        "pyproject.toml": pyproject.get("project", {}).get("version"),
        "settings.py": _runtime_version(),
        "pfsense-overview widget": _json(
            "widgets/pfsense-overview/widget.manifest.json"
        ).get("version"),
        "pfsense-overview package": _json("widgets/pfsense-overview/package.json").get(
            "version"
        ),
        "pfsense-client-security widget": _json(
            "widgets/pfsense-client-security/widget.manifest.json"
        ).get("version"),
        "pfsense-client-security package": _json(
            "widgets/pfsense-client-security/package.json"
        ).get("version"),
    }
    mismatches = [
        f"{source}={value!r}" for source, value in sources.items() if value != version
    ]
    expected_image = f"piphinetwork/piphi-network-pfsense:{version}"
    if manifest.get("image") != expected_image:
        mismatches.append(f"manifest image={manifest.get('image')!r}")
    runtime_image = (
        manifest.get("runtime", {}).get("linux", {}).get("container", {}).get("image")
    )
    if runtime_image != expected_image:
        mismatches.append(f"manifest runtime image={runtime_image!r}")
    if mismatches:
        raise SystemExit(
            f"Release tag {args.tag} does not match release metadata:\n"
            + "\n".join(f"- {item}" for item in mismatches)
        )
    print(f"Release metadata is consistent for {args.tag}")


if __name__ == "__main__":
    main()
