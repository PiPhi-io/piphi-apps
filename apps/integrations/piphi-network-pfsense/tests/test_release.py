from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_RELEASE = ROOT / "scripts" / "check_release.py"
RELEASE_WORKFLOW = ROOT / ".github/workflows/release.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"


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


def test_release_dispatch_runs_from_main_but_builds_the_tag() -> None:
    workflow = RELEASE_WORKFLOW.read_text()

    assert "workflow_dispatch:" in workflow
    assert "release_ref:" in workflow
    assert "ref: refs/tags/${{ env.RELEASE_REF }}" in workflow
    assert 'pdm run python scripts/check_release.py "${RELEASE_REF}"' in workflow
    assert "artifact-metadata: write" in workflow


def test_linux_workflows_use_the_dedicated_self_hosted_runner() -> None:
    expected_runner = "[self-hosted, Linux, X64, self-hosted-machine-1]"

    assert expected_runner in CI_WORKFLOW.read_text()
    assert expected_runner in RELEASE_WORKFLOW.read_text()
    assert "ubuntu-latest" not in CI_WORKFLOW.read_text()
    assert "ubuntu-latest" not in RELEASE_WORKFLOW.read_text()


def test_ci_avoids_duplicate_feature_branch_push_runs() -> None:
    workflow = CI_WORKFLOW.read_text()

    assert "pull_request:" in workflow
    assert "push:\n    branches: [main]" in workflow


def test_widget_production_dependencies_are_audited_in_ci_and_release() -> None:
    assert CI_WORKFLOW.read_text().count("npm audit --omit=dev") == 2
    assert "npm audit --omit=dev --prefix" in RELEASE_WORKFLOW.read_text()


def test_release_keeps_assets_in_one_job_without_actions_artifact_handoff() -> None:
    workflow = RELEASE_WORKFLOW.read_text()

    assert "name: Verify, publish, and release" in workflow
    assert "actions/upload-artifact" not in workflow
    assert "actions/download-artifact" not in workflow
    assert (
        "softprops/action-gh-release@5be0e66d93ac7ed76da52eca8bb058f665c3a5fe"
        in workflow
    )
    assert "tag_name: ${{ env.RELEASE_REF }}" in workflow
    assert "fail_on_unmatched_files: true" in workflow
    assert "files: release/*" in workflow
    assert "gh release create" not in workflow


def test_trusted_ci_and_release_use_the_scoped_docker_organization_token() -> None:
    release_workflow = RELEASE_WORKFLOW.read_text()
    ci_workflow = CI_WORKFLOW.read_text()

    assert "username: piphinetwork" in release_workflow
    assert "password: ${{ secrets.DOCKERHUB_TOKEN }}" in release_workflow
    assert "DOCKERHUB_OIDC_CONNECTIONID" not in release_workflow
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository"
        in ci_workflow
    )
    assert "username: piphinetwork" in ci_workflow
    assert "password: ${{ secrets.DOCKERHUB_TOKEN }}" in ci_workflow
