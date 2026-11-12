"""Generate a reviewable registry entry from the authoritative local manifest."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_entry(manifest: dict) -> dict:
    return {
        "id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
        "type": "integration", "deployment_mode": "standalone",
        "trust_level": "experimental", "risk_level": "moderate",
        "description": manifest["description"], "rewardable": False,
        "platforms": manifest["platforms"], "image": manifest["image"],
        "icon_url": "https://raw.githubusercontent.com/PiPhi-io/piphi-nework-registry/main/icons/placeholder.svg",
        "owner": "PiPhi-io", "repo_name": "piphi-network-plex",
        "repo_url": "https://github.com/PiPhi-io/piphi-network-plex",
        "manifest_path": "manifest.json",
        "tags": ["plex", "media", "media-library", "dashboard", "widget-sdk"],
        "runtime_requirements": ["secrets_or_api_tokens"],
        "maintainer": {"name": "PiPhi Network", "website": "https://piphi.io", "support_email": "support@piphi.io"},
        "marketplace": manifest["marketplace"],
    }


if __name__ == "__main__":
    print(json.dumps(build_entry(json.loads((ROOT / "manifest.json").read_text())), indent=2))
