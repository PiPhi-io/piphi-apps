from __future__ import annotations

import json
from pathlib import Path

from piphi_network_sense.contract import CAPABILITIES, COMMANDS, CONFIG_SCHEMA, REQUIRED_ENDPOINTS
from piphi_network_sense.main import app


def test_runtime_implements_contract_routes() -> None:
    routes = set(app.openapi()["paths"])
    for path in [
        "/health",
        "/diagnostics",
        "/discover",
        "/config",
        "/config/sync",
        "/deconfigure",
        "/deconfigure/{config_id}",
        "/ui-config",
        "/entities",
        "/state",
        "/contract",
        "/events",
        "/events/device/{config_id}/example",
        "/telemetry/example",
        "/telemetry/device/{config_id}/example",
        "/command",
    ]:
        assert path in routes

    assert REQUIRED_ENDPOINTS == ["health", "entities", "command", "config", "ui_config"]
    assert "refresh" in COMMANDS
    assert "active_power_w" in CAPABILITIES
    assert CAPABILITIES["always_on_power_w"]["unit"] == "W"
    assert CAPABILITIES["other_power_w"]["unit"] == "W"


def test_manifest_declares_single_instance_and_experience_package() -> None:
    manifest = json.loads((Path(__file__).parents[1] / "manifest.json").read_text())
    assert manifest["config"]["maximum_instances"] == 1
    assert manifest["identity"]["fields"] == ["email"]
    assert manifest["ui"]["experience_packages"] == [
        {
            "registry_id": "io.piphi.sense-energy",
            "version_range": ">=0.1,<1",
            "auto_install": True,
        }
    ]
    assert set(manifest["capabilities"]) == set(CAPABILITIES)


def test_experience_package_exposes_monitor_and_appliance_widgets() -> None:
    package = json.loads(
        (Path(__file__).parents[1] / "experiences/sense-energy/package.source.json").read_text()
    )
    assert package["owning_integration_id"] == "piphi-network-sense"
    assert package["identity"]["version"] == "0.2.21"
    widgets = {widget["id"]: widget for widget in package["widgets"]}
    assert set(widgets) == {"energy-overview", "appliance-energy"}
    monitor_capabilities = {
        capability
        for slot in widgets["energy-overview"]["binding_slots"]
        for capability in slot["capability_requirements"]
    }
    assert {"active_power_w", "active_solar_power_w", "daily_usage_kwh"} <= monitor_capabilities
    appliance_capabilities = {
        capability
        for slot in widgets["appliance-energy"]["binding_slots"]
        for capability in slot["capability_requirements"]
    }
    assert appliance_capabilities == {"device_power_w", "device_daily_energy_kwh"}
    assert widgets["energy-overview"]["runtime"] == "sandboxed_bundle"
    assert widgets["energy-overview"]["entry"] == "assets/energy-overview.js"
    assert "recipe" not in widgets["energy-overview"]
    assert widgets["appliance-energy"]["runtime"] == "declarative"
    assert widgets["appliance-energy"]["binding_slots"][0]["label"] == "Current power"
    assert widgets["appliance-energy"]["recipe"]["items"][0]["label"] == "Now"


def test_energy_overview_uses_a_truly_transparent_theme_canvas() -> None:
    stylesheet = (
        Path(__file__).parents[1]
        / "experiences/sense-energy/themes/sense-overview.css"
    ).read_text()
    assert "html,\nbody,\n#piphi-widget-root,\n.sense-overview" in stylesheet
    assert "background: transparent !important" in stylesheet
    assert "background: #fff" not in stylesheet
    assert 'border-inline-start: 2px solid var(--sense-orange-accent)' in stylesheet
    assert "border-top: 1px solid color-mix(in srgb, var(--sense-border) 72%, transparent)" in stylesheet
    assert ':root[data-piphi-color-scheme="dark"] .live-panel' in stylesheet
    assert ':root[data-piphi-color-scheme="dark"] .today-panel' in stylesheet
    assert "color-scheme:" not in stylesheet
    assert "var(--piphi-widget-text" in stylesheet


def test_energy_overview_text_orange_meets_wcag_aa_on_white() -> None:
    def luminance(hex_color: str) -> float:
        channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    foreground = luminance("#b9381b")
    background = luminance("#ffffff")
    contrast = (background + 0.05) / (foreground + 0.05)
    assert contrast >= 4.5

    dark_foreground = luminance("#ff8a6f")
    for dark_background in ("#0f172a", "#111827", "#1e293b"):
        background = luminance(dark_background)
        contrast = (dark_foreground + 0.05) / (background + 0.05)
        assert contrast >= 4.5

    stylesheet = (
        Path(__file__).parents[1]
        / "experiences/sense-energy/themes/sense-overview.css"
    ).read_text()
    assert ':root[data-piphi-color-scheme="dark"] { --sense-orange: #ff8a6f; }' in stylesheet


def test_energy_overview_uses_a_glance_sized_live_panel() -> None:
    root = Path(__file__).parents[1] / "experiences/sense-energy"
    stylesheet = (root / "themes/sense-overview.css").read_text()
    script = (root / "assets/energy-overview.js").read_text()
    assert "grid-template-rows: auto 4.7rem auto" in stylesheet
    assert "align-content: start" in stylesheet
    assert "const minimumGlanceHeight = 168" in script
    assert "Math.max(" in script
    assert "host.ready({ height: measuredContentHeight() })" in script
    assert "new ResizeObserver(reportContentHeight)" in script
    assert "host.setHeight(measuredContentHeight())" in script
    assert "background-panel" not in script
    assert "Live household demand" not in script
    assert 'root.querySelector(".data-status").hidden = true' in script


def test_energy_overview_uses_one_state_subscription_instead_of_polling() -> None:
    script = (
        Path(__file__).parents[1]
        / "experiences/sense-energy/assets/energy-overview.js"
    ).read_text()
    assert "host.subscribeState({ capabilityIds }" in script
    assert "host.getCapabilityState" not in script
    assert "setInterval" not in script


def test_energy_overview_uses_the_core_widget_type_scale() -> None:
    root = Path(__file__).parents[1] / "experiences/sense-energy"
    stylesheet = (root / "themes/sense-overview.css").read_text()
    script = (root / "assets/energy-overview.js").read_text()

    for token in [
        "--piphi-widget-font-size-label",
        "--piphi-widget-font-size-title",
        "--piphi-widget-font-size-value",
        "--piphi-widget-font-size-hero",
    ]:
        assert token in stylesheet
    assert ".hero-value strong { font-size: var(--sense-type-hero)" in stylesheet
    assert ".solar-reading strong { font-size: var(--sense-type-hero)" in stylesheet
    assert ".today-readings strong { font-size: var(--sense-type-value)" in stylesheet
    assert "clamp(" not in stylesheet
    assert 'class="solar-value"' in script


def test_energy_overview_reflows_instead_of_squeezing_narrow_cards() -> None:
    stylesheet = (
        Path(__file__).parents[1]
        / "experiences/sense-energy/themes/sense-overview.css"
    ).read_text()

    assert "@container (max-width: 13rem)" in stylesheet
    assert ".live-panel { grid-template-columns: 1fr;" in stylesheet
    assert ".today-readings { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in stylesheet
    assert ".today-readings button:nth-child(3)" in stylesheet
    assert "grid-column: 1 / -1" in stylesheet


def test_config_schema_uses_renderer_safe_validation_hints() -> None:
    properties = CONFIG_SCHEMA["schema"]["properties"]
    assert "format" not in properties["email"]
    assert "format" not in properties["password"]
    assert properties["mfa_code"]["default"] == ""
    assert CONFIG_SCHEMA["uiSchema"]["password"]["ui:widget"] == "password"
