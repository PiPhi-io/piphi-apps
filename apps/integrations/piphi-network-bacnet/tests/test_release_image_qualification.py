from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


def _load_qualification_module():
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "bacnet_release_image_qualification",
        root / "scripts" / "qualify_release_image.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_published_image_is_pulled_before_inspection(monkeypatch) -> None:
    module = _load_qualification_module()
    image = "ghcr.io/piphi-io/piphi-network-bacnet@sha256:" + "a" * 64
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        payload = json.dumps(
            [{"Config": {"User": "10001:10001", "Labels": {}}}]
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=payload if command[1:3] == ["image", "inspect"] else "",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.pull_and_inspect_image(image)["Config"]["User"] == "10001:10001"
    assert calls == [
        ["docker", "pull", image],
        ["docker", "image", "inspect", image],
    ]


def test_release_metadata_requires_exact_oci_labels() -> None:
    module = _load_qualification_module()
    source = "https://github.com/PiPhi-io/piphi-apps"
    revision = "a" * 40
    inspected = {
        "Config": {
            "User": "10001:10001",
            "Labels": {
                "org.opencontainers.image.source": source,
                "org.opencontainers.image.revision": revision,
                "org.opencontainers.image.version": "0.1.2",
            },
        }
    }

    module.validate_image_metadata(
        inspected, version="0.1.2", revision=revision, source=source
    )
    inspected["Config"]["Labels"].pop("org.opencontainers.image.revision")
    with pytest.raises(AssertionError, match="org.opencontainers.image.revision"):
        module.validate_image_metadata(
            inspected, version="0.1.2", revision=revision, source=source
        )
