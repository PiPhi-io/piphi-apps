from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


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
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="10001:10001\n" if command[1:3] == ["image", "inspect"] else "",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.pull_and_inspect_image_user(image) == "10001:10001"
    assert calls == [
        ["docker", "pull", image],
        ["docker", "image", "inspect", image, "--format", "{{.Config.User}}"],
    ]
