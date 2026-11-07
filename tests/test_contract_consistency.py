from __future__ import annotations

import json
import tomllib
from pathlib import Path

from piphi_network_thinqconnect import __version__
from piphi_network_thinqconnect.contract.command import router as command_module
from piphi_network_thinqconnect.lib.normalization import (
    DEVICE_TYPE_CATALOG,
    stable_client_id,
)
from piphi_network_thinqconnect.lib.push import REFRIGERATOR_PUSH_EVENTS
from piphi_network_thinqconnect.lib.schemas import ThinQDeviceConfig
from piphi_network_thinqconnect.lib.store import INTEGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]


def _load_json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_stable_client_id_is_account_scoped() -> None:
    account_client_id = stable_client_id(
        access_token="token-1",
        country_code="us",
        device_id="device-a",
    )

    assert account_client_id == stable_client_id(
        access_token="token-1",
        country_code="US",
        device_id="device-b",
    )
    assert account_client_id != stable_client_id(
        access_token="token-2",
        country_code="US",
        device_id="device-a",
    )
    assert account_client_id != stable_client_id(
        access_token="token-1",
        country_code="CA",
        device_id="device-a",
    )


def test_documented_commands_exist_in_manifest_and_behaviors() -> None:
    manifest = _load_json("src/manifest.json")
    behaviors = _load_json("src/behaviors.json")

    manifest_commands = set(manifest.get("commands", {}).keys())
    behavior_commands = {
        option["id"]
        for device in behaviors.get("devices", [])
        for group_name in ("actions", "stop")
        for option in device.get(group_name, [])
    }
    documented_commands = {
        command_id
        for device in DEVICE_TYPE_CATALOG.values()
        for command_id in device.get("documented_commands", [])
    }

    assert documented_commands
    assert documented_commands.issubset(manifest_commands)
    assert documented_commands.issubset(behavior_commands)


def test_refrigerator_capability_catalog_accounts_for_known_surface() -> None:
    catalog = _load_json("src/refrigerator-capability-catalog.json")
    rows = catalog["rows"]
    ids = [row["id"] for row in rows]

    assert len(ids) == len(set(ids))
    assert {row["status"] for row in rows} <= {"implemented", "planned", "excluded"}
    assert {
        "door.open",
        "temperature.target",
        "mode.power_save",
        "mode.eco",
        "mode.sabbath",
        "freezing.rapid",
        "cooling.express_mode",
        "cooling.express_fridge",
        "filter.fresh_air",
        "filter.water",
        "notification",
        "energy.daily",
        "profile.unknown_readable",
        "profile.unknown_writable",
        "events.mqtt_push",
    } == set(ids)
    assert next(row for row in rows if row["id"] == "profile.unknown_writable")[
        "status"
    ] == "excluded"


def test_automation_registry_matches_declared_behavior_commands() -> None:
    behaviors = _load_json("src/behaviors.json")
    declared_commands = {
        option["runtime"]["command"]
        for device in behaviors.get("devices", [])
        for option in device.get("actions", [])
    }
    registered_commands = {
        definition.command
        for definition in command_module.automation_registry.action_definitions
    }

    assert registered_commands == declared_commands


def test_refrigerator_push_events_match_behavior_triggers() -> None:
    behaviors = _load_json("src/behaviors.json")
    refrigerator = next(
        device
        for device in behaviors["devices"]
        if device["id"] == "thinq_refrigerator"
    )
    push_triggers = {
        trigger["runtime"]["event"]
        for trigger in refrigerator["triggers"]
        if trigger["runtime"].get("source") == "lg_thinq_connect_push"
    }

    assert push_triggers == REFRIGERATOR_PUSH_EVENTS
    assert all(
        trigger["capability"] in refrigerator["capabilities"]
        for trigger in refrigerator["triggers"]
        if trigger["runtime"].get("event") in REFRIGERATOR_PUSH_EVENTS
    )
    assert not any(event.startswith("thinq.push.") for event in push_triggers)


def test_refrigerator_behaviors_cover_reviewed_safe_state_surface() -> None:
    behaviors = _load_json("src/behaviors.json")
    refrigerator = next(
        device
        for device in behaviors["devices"]
        if device["id"] == "thinq_refrigerator"
    )
    condition_fields = {
        condition["runtime"]["field"] for condition in refrigerator["conditions"]
    }

    assert {
        "door_open",
        "target_temperature",
        "filter_life",
        "power_save_enabled",
        "eco_friendly_enabled",
        "sabbath_mode_enabled",
        "rapid_freeze_enabled",
        "express_mode_enabled",
        "express_fridge_enabled",
        "fresh_air_filter_mode",
        "water_filter_state",
        "notification",
    }.issubset(condition_fields)


def test_push_opt_in_is_declared_by_runtime_and_manifest() -> None:
    manifest = _load_json("src/manifest.json")
    platform_inputs = [
        platform["discovery"]["inputs"]
        for platform in manifest["runtime"].values()
    ]

    assert ThinQDeviceConfig.model_fields["push_events_enabled"].default is False
    for inputs in platform_inputs:
        push_field = next(
            field for field in inputs if field["name"] == "push_events_enabled"
        )
        assert push_field["default"] is False


def test_behavior_capabilities_exist_in_manifest() -> None:
    manifest = _load_json("src/manifest.json")
    behaviors = _load_json("src/behaviors.json")

    manifest_capabilities = set(manifest.get("capabilities", {}).keys())
    behavior_capabilities = {
        capability
        for device in behaviors.get("devices", [])
        for capability in device.get("capabilities", [])
    }

    assert behavior_capabilities
    assert behavior_capabilities.issubset(manifest_capabilities)


def test_temperature_capabilities_use_runtime_reported_units() -> None:
    manifest = _load_json("src/manifest.json")

    assert "unit" not in manifest["capabilities"]["temperature"]
    assert "unit" not in manifest["capabilities"]["target_temperature"]


def test_target_temperature_supports_history_charts() -> None:
    manifest = _load_json("src/manifest.json")

    allowed_widgets = manifest["capabilities"]["target_temperature"]["dashboard"][
        "allowed_widgets"
    ]
    assert "line-chart" in allowed_widgets


def test_temperature_behaviors_use_correct_state_fields_operators_and_bounds() -> None:
    behaviors = _load_json("src/behaviors.json")

    for device in behaviors.get("devices", []):
        for condition in device.get("conditions", []):
            condition_id = condition.get("id")
            if condition_id not in {
                "temperature_above",
                "temperature_below",
                "target_temperature_above",
                "target_temperature_below",
            }:
                continue
            expected_field = (
                "target_temperature"
                if condition_id.startswith("target_temperature")
                else "temperature"
            )
            expected_operator = "<" if condition_id.endswith("below") else ">"
            assert condition["runtime"]["field"] == expected_field
            assert condition["runtime"]["operator"] == expected_operator

        for action in device.get("actions", []):
            if action.get("id") != "set_target_temperature":
                continue
            temperature = next(
                param for param in action["params"] if param["name"] == "temperature"
            )
            assert isinstance(temperature.get("min"), (int, float))
            assert isinstance(temperature.get("max"), (int, float))
            assert temperature["min"] < temperature["max"]


def test_integration_and_widget_manifests_share_the_interaction_contract() -> None:
    integration_manifest = _load_json("src/manifest.json")
    widget_manifest = _load_json(
        "widgets/thinqconnect-overview/widget.manifest.json"
    )
    advertised_widget = integration_manifest["ui"]["widget_packages"][0]

    assert advertised_widget["version"] == widget_manifest["version"]
    assert advertised_widget["layout"] == {
        **widget_manifest["layout"],
        "transparent": True,
    }
    assert advertised_widget["security"] == widget_manifest["security"]
    assert (
        advertised_widget["interaction_targets"]
        == widget_manifest["interaction_targets"]
    )


def test_all_runtime_and_widget_version_projections_match() -> None:
    integration_manifest = _load_json("src/manifest.json")
    widget_manifest = _load_json("widgets/thinqconnect-overview/widget.manifest.json")
    widget_package = _load_json("widgets/thinqconnect-overview/package.json")
    widget_lock = _load_json("widgets/thinqconnect-overview/package-lock.json")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = pyproject["project"]["version"]

    assert integration_manifest["version"] == expected
    assert integration_manifest["ui"]["widget_packages"][0]["version"] == expected
    assert widget_manifest["version"] == expected
    assert widget_package["version"] == expected
    assert widget_lock["version"] == expected
    assert widget_lock["packages"][""]["version"] == expected
    assert __version__ == expected
    assert INTEGRATION_VERSION == expected


def test_release_image_binds_source_manifest_and_behavior_provenance() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    required_labels = {
        "org.opencontainers.image.version": "RELEASE_VERSION",
        "org.opencontainers.image.revision": "SOURCE_REVISION",
        "org.opencontainers.image.source": "SOURCE_REPOSITORY",
        "io.piphi.manifest.sha256": "MANIFEST_SHA256",
        "io.piphi.behaviors.sha256": "BEHAVIORS_SHA256",
    }
    workflow_labels = {
        "org.opencontainers.image.version=${{ steps.version.outputs.version }}",
        "org.opencontainers.image.revision=${{ steps.contracts.outputs.revision }}",
        "org.opencontainers.image.source=https://github.com/PiPhi-io/piphi-network-thinqconnect",
        "io.piphi.manifest.sha256=${{ steps.contracts.outputs.manifest_sha256 }}",
        "io.piphi.behaviors.sha256=${{ steps.contracts.outputs.behaviors_sha256 }}",
    }

    for label, build_argument in required_labels.items():
        assert f'ARG {build_argument}=' in dockerfile
        assert f'{label}="${{{build_argument}}}"' in dockerfile
    for label in workflow_labels:
        assert label in workflow
    assert "revision=$(git rev-parse HEAD)" in workflow
    assert "manifest_sha256=$(sha256sum src/manifest.json" in workflow
    assert "behaviors_sha256=$(sha256sum src/behaviors.json" in workflow
    assert "SOURCE_REVISION=${{ steps.contracts.outputs.revision }}" in workflow
    assert "MANIFEST_SHA256=${{ steps.contracts.outputs.manifest_sha256 }}" in workflow
    assert "BEHAVIORS_SHA256=${{ steps.contracts.outputs.behaviors_sha256 }}" in workflow
    assert workflow.index("Validate bumped release contract") < workflow.index(
        "Commit release metadata"
    )
    assert workflow.index("Publish immutable release revision") < workflow.index(
        "Build and push image"
    )


def test_release_workflow_can_publish_an_existing_tag_without_mutating_source() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "existing_tag:" in workflow
    assert "permissions: {}" in workflow
    assert "preflight:" in workflow
    assert "contents: read" in workflow
    assert "Require default branch dispatch" in workflow
    assert '[[ "${GITHUB_REF_NAME}" == "${{ github.event.repository.default_branch }}" ]]' in workflow
    assert '[[ "${EXISTING_TAG}" =~ ^v(0|[1-9][0-9]*)' in workflow
    assert 'git fetch --no-tags origin "refs/tags/${EXISTING_TAG}"' in workflow
    assert 'TAG_COMMIT=$(git rev-parse "FETCH_HEAD^{commit}")' in workflow
    assert "needs: preflight" in workflow
    assert "ref: ${{ needs.preflight.outputs.tag_commit || github.ref }}" in workflow
    assert '[[ "${EXISTING_TAG}" == "${TAG}" ]]' in workflow
    assert '[[ "$(git rev-parse HEAD)" == "${TAG_COMMIT}" ]]' in workflow
    assert '[[ "$(git rev-parse "FETCH_HEAD^{commit}")" == "${TAG_COMMIT}" ]]' in workflow
    assert workflow.count("if: ${{ needs.preflight.outputs.existing_tag == '' }}") == 2
    assert "DOCKERHUB_OIDC_EXPIREIN: 21600" in workflow
    assert workflow.index("Resolve existing release tag") < workflow.index("Install and test")
    assert workflow.index("Validate bumped release contract") < workflow.index(
        "Build and push image"
    )
