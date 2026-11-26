from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest


def test_published_digest_is_pulled_before_local_metadata_inspection(monkeypatch) -> None:
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "airthings_qualify_release_image",
        root / "scripts" / "qualify_release_image.py",
    )
    assert spec is not None and spec.loader is not None
    qualification = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = qualification
    spec.loader.exec_module(qualification)

    image = "ghcr.io/piphi-io/airthings-consumer-cloud@sha256:" + "a" * 64
    commands: list[tuple[str, ...]] = []
    inspected = json.dumps(
        [
            {
                "Config": {
                    "User": "piphi",
                    "Volumes": {"/var/lib/piphi": {}},
                    "Labels": {
                        "org.opencontainers.image.version": "0.1.8",
                        "org.opencontainers.image.revision": "revision",
                        "io.piphi.manifest.sha256": "manifest",
                        "io.piphi.behaviors.sha256": "behaviors",
                    },
                }
            }
        ]
    )

    def capture_command(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        del check
        commands.append(command)
        stdout = inspected if command[:3] == ("docker", "image", "inspect") else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(qualification, "run_command", capture_command)
    qualification.validate_image_metadata(
        image,
        version="0.1.8",
        revision="revision",
        manifest_sha256="manifest",
        behaviors_sha256="behaviors",
    )

    assert commands == [
        ("docker", "pull", image),
        ("docker", "image", "inspect", image),
    ]


def test_manifest_and_behaviors_align() -> None:
    root = Path(__file__).resolve().parent.parent / "src"
    manifest = json.loads((root / "manifest.json").read_text())
    behaviors = json.loads((root / "behaviors.json").read_text())

    manifest_capabilities = set(manifest["entities"][0]["capabilities"])
    behavior_capabilities = set(behaviors["devices"][0]["capabilities"])

    assert manifest["id"] == "airthings-consumer-cloud-api"
    assert manifest["api"]["endpoints"]["config_sync"] == "/configs/sync"
    assert manifest["ui"]["experience_packages"] == [
        {
            "registry_id": "io.piphi.airthings-air-quality",
            "version_range": ">=0.1,<1",
            "auto_install": True,
        }
    ]
    assert behavior_capabilities == manifest_capabilities
    assert manifest["runtime_requirements"] == [
        "cloud_account",
        "internet_access",
        "secrets_or_api_tokens",
    ]
    assert manifest["marketplace"]["metadata_version"] == 2
    assert manifest["marketplace"]["quality_tier"] == "bronze"
    assert manifest["marketplace"]["governance"] == {
        "schema_version": 1,
        "publication_status": "beta",
        "rollout_percent": 1,
        "lifecycle_status": "active",
        "qualification": {"status": "unverified"},
    }

    device = behaviors["devices"][0]
    conditions = {condition["id"]: condition for condition in device["conditions"]}
    above_params = {item["name"]: item for item in conditions["metric_above"]["params"]}
    below_params = {item["name"]: item for item in conditions["metric_below"]["params"]}
    assert above_params["metric"]["default"] == "co2_ppm"
    assert above_params["value"]["default"] == 1000
    assert below_params["metric"]["default"] == "battery_percent"
    assert below_params["value"]["default"] == 20
    trigger_events = {trigger["runtime"]["event"] for trigger in device["triggers"]}
    assert {
        "device.state_changed",
        "airthings.cloud.sample.failed",
        "airthings.cloud.sample.recovered",
        "airthings.cloud.device.removed",
    } <= trigger_events

    template_action = behaviors["templates"][0]["config"]["actions"][0]
    assert template_action["action"] == "builtin.notification.send"
    assert "capability" not in template_action
    assert "sourceRef" not in template_action
    assert "target" not in template_action
    assert template_action["runtime"] == {
        "command": "builtin.notification.send",
        "semanticType": "notification",
        "actionContractVersion": 1,
    }
    assert template_action["parameters"]["title"]
    assert "channel" not in template_action["parameters"]


def test_all_release_version_projections_match() -> None:
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "src" / "manifest.json").read_text())
    catalog = json.loads((root / "docs" / "capability-catalog.json").read_text())
    package = json.loads(
        (root / "experiences" / "air-quality" / "package.source.json").read_text()
    )
    pyproject_text = (root / "pyproject.toml").read_text()
    project_version = next(
        line.split('"')[1]
        for line in pyproject_text.splitlines()
        if line.startswith("version = ")
    )

    assert manifest["version"] == project_version
    assert catalog["catalog_version"] == project_version
    assert package["identity"]["version"] == project_version
    assert manifest["runtime"]["linux"]["container"]["image"].endswith(
        f":{project_version}"
    )


def test_release_script_updates_catalog_and_experience_versions() -> None:
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "airthings_release", root / "scripts" / "release.py"
    )
    assert spec is not None and spec.loader is not None
    release = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = release
    spec.loader.exec_module(release)
    catalog = {"catalog_version": "0.1.5"}
    package = {"identity": {"version": "0.1.5"}}

    release.update_release_projections(
        catalog=catalog,
        experience_package=package,
        version="0.1.6",
    )

    assert catalog["catalog_version"] == "0.1.6"
    assert package["identity"]["version"] == "0.1.6"


def test_release_image_binds_source_manifest_and_behavior_provenance() -> None:
    root = Path(__file__).resolve().parent.parent
    dockerfile = (root / "Dockerfile").read_text()
    workflow = (root.parents[2] / ".github" / "workflows" / "release-app.yml").read_text()
    required_labels = {
        "org.opencontainers.image.version": "RELEASE_VERSION",
        "org.opencontainers.image.revision": "SOURCE_REVISION",
        "org.opencontainers.image.source": "SOURCE_REPOSITORY",
        "io.piphi.manifest.sha256": "MANIFEST_SHA256",
        "io.piphi.behaviors.sha256": "BEHAVIORS_SHA256",
    }
    for label, build_argument in required_labels.items():
        assert f"ARG {build_argument}=" in dockerfile
        assert f'{label}="${{{build_argument}}}"' in dockerfile
    assert "SOURCE_REVISION=${{ github.sha }}" in workflow
    assert "SOURCE_REPOSITORY=https://github.com/PiPhi-io/piphi-apps" in workflow
    assert "manifest_sha256=$(sha256sum" in workflow
    assert "behaviors_sha256=$(sha256sum src/behaviors.json" in workflow


def test_locked_build_pins_base_image_and_declares_read_only_runtime() -> None:
    root = Path(__file__).resolve().parent.parent
    dockerfile = (root / "Dockerfile").read_text()
    manifest = json.loads((root / "src" / "manifest.json").read_text())

    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 2
    assert all("python:3.12-slim@sha256:" in line for line in from_lines)
    assert "pip install --upgrade pip" not in dockerfile
    assert "pip install --no-deps ." not in dockerfile
    assert "pdm==2.29.7" in dockerfile
    assert "--require-hashes" in dockerfile
    assert manifest["runtime"]["linux"]["container"]["read_only"] is True
    assert '"--read-only"' in (root / "scripts" / "qualify_release_image.py").read_text()


def test_release_workflow_uses_protected_monorepo_publication() -> None:
    root = Path(__file__).resolve().parent.parent
    workflow = (root.parents[2] / ".github" / "workflows" / "release-app.yml").read_text()

    assert "Require the protected default branch" in workflow
    assert "Ensure release tag does not exist" in workflow
    assert '"registry": "ghcr.io"' in (root / "piphi-app.json").read_text()


def test_release_workflow_qualifies_exact_image_before_publishing_revision() -> None:
    root = Path(__file__).resolve().parent.parent
    workflow = (root.parents[2] / ".github" / "workflows" / "release-app.yml").read_text()

    assert "Build and qualify Airthings release candidate" in workflow
    assert "Qualify immutable published Airthings image" in workflow
    assert "pdm run python scripts/qualify_release_image.py" in workflow
    assert "--image '${{ needs.plan.outputs.image }}@${{ steps.build.outputs.digest }}'" in workflow
    assert "--version '${{ needs.plan.outputs.version }}'" in workflow
    assert "--revision '${{ github.sha }}'" in workflow
    assert "--manifest-sha256 '${{ steps.contracts.outputs.manifest_sha256 }}'" in workflow
    assert "--behaviors-sha256 '${{ steps.contracts.outputs.behaviors_sha256 }}'" in workflow
    assert workflow.index("Build and qualify Airthings release candidate") < workflow.index(
        "Build and optionally publish"
    ) < workflow.index("Qualify immutable published Airthings image")
    assert workflow.count("uses: docker/build-push-action@v6") == 1


def test_capability_catalog_marks_declared_scope_implementation_complete() -> None:
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "src" / "manifest.json").read_text())
    catalog = json.loads((root / "docs" / "capability-catalog.json").read_text())
    rows = {row["id"]: row for row in catalog["capabilities"]}

    assert catalog["integration_id"] == manifest["id"]
    assert catalog["catalog_version"] == manifest["version"]
    assert catalog["completion"] == {
        "status": "implementation_complete",
        "scope": "Airthings Consumer Cloud devices and readings declared by this integration",
        "automated_validation": "passed",
        "provider_contract_validation": "passed",
        "exact_image_validation": "required",
        "physical_device_validation": "optional_follow_up",
    }
    assert set(manifest["capabilities"]) <= rows.keys()
    assert all(rows[capability]["status"] == "implemented" for capability in manifest["capabilities"])
    assert set(manifest["commands"]) == {
        row["id"] for row in catalog["commands"] if row["status"] == "implemented"
    }
    trigger_events = {
        trigger["runtime"]["event"]
        for trigger in json.loads((root / "src" / "behaviors.json").read_text())["devices"][0]["triggers"]
    }
    assert trigger_events == {
        row["id"] for row in catalog["events"] if row["status"] == "implemented"
    }


def test_air_quality_experience_matches_integration_capabilities() -> None:
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / "src" / "manifest.json").read_text())
    package = json.loads(
        (root / "experiences" / "air-quality" / "package.source.json").read_text()
    )

    assert package["sdk_version_range"] == ">=0.6.1,<0.7"
    assert package["owning_integration_id"] == manifest["id"]
    required = {
        capability
        for slot in package["widgets"][0]["binding_slots"]
        for capability in slot["capability_requirements"]
    }
    assert required <= set(manifest["capabilities"])
    slots = {
        slot["id"]: slot
        for slot in package["widgets"][0]["binding_slots"]
    }
    assert slots["temperature"]["required"] is True
    assert slots["humidity"]["required"] is False
    assert slots["radon"]["required"] is False
    assert slots["co2"]["required"] is False
    widget = package["widgets"][0]
    assert widget["presentation"]["shell"] == "core"
    targets = widget["interaction_targets"]
    assert len(targets) == 5
    assert {target["binding_slot_id"] for target in targets if target["kind"] == "binding"} == set(slots)
    assert all(target["default_action"] == "more-info" for target in targets if target["kind"] == "binding")
    assert all("command" not in target["allowed_actions"] for target in targets)
    assert widget["core_card_replacements"] == [
        {
            "schema_version": "1",
            "id": "airthings-air-quality-v1",
            "source_card_types": ["sensor-card", "stat"],
            "source_capability_ids": [
                "temperature_c",
                "humidity_percent",
                "radon_short_term_bqm3",
                "co2_ppm",
            ],
            "strategy": "same-device",
        }
    ]
    assert widget["default_theme_id"] == "airthings"
    assert {theme["id"] for theme in widget["themes"]} == {"airthings", "quiet"}
    assert all(item["action"]["type"] == "details" for item in widget["recipe"]["items"])
    branded_theme = (root / "experiences" / "air-quality" / "themes" / "airthings.css").read_text()
    assert "--piphi-experience-shadow: none;" in branded_theme
    assert "--piphi-experience-tile-shadow: none;" in branded_theme


def test_air_quality_release_archive_contains_normalized_theme_contract() -> None:
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "airthings_build_experience", root / "scripts" / "build_experience.py"
    )
    assert spec is not None and spec.loader is not None
    build_experience = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_experience)
    source = json.loads(
        (root / "experiences" / "air-quality" / "package.source.json").read_text()
    )
    normalized = build_experience._normalized(source)
    widget = normalized["widgets"][0]

    assert widget["themes"]
    assert all(
        slot["data_delivery"]
        == {"mode": "stream_preferred", "stale_after_seconds": None}
        for slot in widget["binding_slots"]
    )
    with ZipFile(io.BytesIO(build_experience._archive(normalized))) as package:
        assert {
            "package.source.json",
            "themes/airthings.css",
            "themes/quiet.css",
        } <= set(package.namelist())


def test_experience_check_build_is_branch_safe_but_release_build_requires_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "airthings_build_experience_release_ref", root / "scripts" / "build_experience.py"
    )
    assert spec is not None and spec.loader is not None
    build_experience = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_experience)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    build_experience.build(tmp_path, check=True, env_name="unused", key_id="test-key")
    with pytest.raises(SystemExit, match="does not match package version"):
        build_experience.build(tmp_path, check=False, env_name="unused", key_id="test-key")
