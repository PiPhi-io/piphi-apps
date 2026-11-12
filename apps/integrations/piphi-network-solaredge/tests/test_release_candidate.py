from __future__ import annotations

import json
import tomllib
from pathlib import Path

from solar_edge.settings import INTEGRATION_VERSION

ROOT = Path(__file__).parents[1]


def test_release_versions_and_image_are_synchronized() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = project["project"]["version"]
    assert version == manifest["version"] == INTEGRATION_VERSION == "0.2.2"
    assert manifest["image"].endswith(f":{version}")
    assert manifest["runtime"]["linux"]["container"]["image"] == manifest["image"]
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]["src/behaviors.json"] == "solar_edge/behaviors.json"


def test_container_no_longer_embeds_or_serves_widget_bundles() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    app_source = (ROOT / "src" / "solar_edge" / "app.py").read_text()
    assert "FROM node" not in dockerfile
    assert "COPY widgets" not in dockerfile
    assert "PIPHI_WIDGET_DIR" not in dockerfile + app_source
    assert "USER piphi" in dockerfile
    assert "HEALTHCHECK" in dockerfile


def test_capability_catalog_accounts_for_manifest_contract() -> None:
    catalog = json.loads((ROOT / "docs" / "capability-catalog.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    rows = {row["id"]: row for row in catalog["capabilities"]}
    assert set(manifest["capabilities"]) <= rows.keys()
    assert all(rows[capability]["status"] == "implemented" for capability in manifest["capabilities"])
    assert {row["status"] for row in rows.values()} == {"implemented", "planned", "excluded"}
    assert catalog["completion"] == {
        "status": "release_candidate",
        "scope": "Read-only SolarEdge Monitoring API V1 aggregate-site telemetry",
        "automated_validation": "passed",
        "physical_site_validation": "pending",
        "blocking_item": "oauth_v2",
    }
    assert rows[catalog["completion"]["blocking_item"]]["status"] == "planned"


def test_solaredge_theme_does_not_restore_dashboard_shell_shadows() -> None:
    theme = (ROOT / "experiences" / "solar-energy" / "themes" / "solaredge.css").read_text()
    assert "--piphi-experience-shadow: none;" in theme
    assert "--piphi-experience-tile-shadow: none;" in theme


def test_release_workflows_publish_only_prepared_immutable_refs() -> None:
    runtime_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    experience_workflow = (ROOT / ".github" / "workflows" / "release-experience.yml").read_text()
    assert "release_ref:" in runtime_workflow
    assert "ref: ${{ inputs.release_ref }}" in runtime_workflow
    assert "git commit" not in runtime_workflow and "git tag" not in runtime_workflow
    assert "RELEASE_IMAGE: piphinetwork/piphi-network-solaredge" in runtime_workflow
    assert "docker/login-action@v4" in runtime_workflow
    assert '"experience-solar-energy-v*.*.*"' in experience_workflow
    assert "PIPHI_WIDGET_SIGNING_KEY_PEM_BASE64" in experience_workflow
