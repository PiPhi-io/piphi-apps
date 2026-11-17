from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
CHECK_RELEASE = ROOT / "scripts" / "check_release.py"
RELEASE_WORKFLOW = REPO_ROOT / ".github/workflows/release-app.yml"
CI_WORKFLOW = REPO_ROOT / ".github/workflows/apps-ci.yml"


def test_current_release_metadata_is_consistent() -> None:
    version = json.loads((ROOT / "manifest.json").read_text())["version"]
    result = subprocess.run(
        [sys.executable, str(CHECK_RELEASE), f"v{version}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_release_check_rejects_a_mismatched_tag() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_RELEASE), "v9.9.9"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not match release metadata" in result.stderr


def test_central_release_dispatch_is_explicit_and_dry_by_default() -> None:
    workflow = RELEASE_WORKFLOW.read_text()

    assert "workflow_dispatch:" in workflow
    assert "package_id:" in workflow
    assert "version:" in workflow
    assert "publish:" in workflow
    assert "default: false" in workflow
    assert "artifact-metadata: write" in workflow


def test_central_ci_covers_pull_requests_and_main_pushes() -> None:
    workflow = CI_WORKFLOW.read_text()

    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches:" in workflow
    assert "main" in workflow
