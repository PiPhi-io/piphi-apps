import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "experiences" / "sense-energy" / "package.source.json"
APPLICABLE_GATES = {
    "runtime",
    "persistence",
    "binding",
    "states",
    "responsive",
    "themes",
    "accessibility",
    "save-reload",
    "performance",
}


def _widgets() -> dict[str, dict]:
    package = json.loads(SOURCE.read_text(encoding="utf-8"))
    return {widget["id"]: widget for widget in package["widgets"]}


def test_every_sense_experience_has_complete_certification_evidence() -> None:
    for widget in _widgets().values():
        certification = widget["certification"]
        assert set(certification["verified_gates"]) == APPLICABLE_GATES
        assert set(certification["evidence"]) == APPLICABLE_GATES
        assert all(certification["evidence"].values())


def test_energy_overview_binding_and_states() -> None:
    source = (SOURCE.parent / "assets" / "energy-overview.js").read_text(
        encoding="utf-8"
    )
    for marker in (
        "await host.getBindings()",
        "await host.subscribeState",
        'event?.kind === "snapshot"',
        'event?.kind === "error"',
        "Some Sense readings are unavailable",
        "Sense readings are temporarily unavailable",
        "Choose a Sense monitor in card settings",
    ):
        assert marker in source


def test_energy_overview_presentation() -> None:
    source = (SOURCE.parent / "assets" / "energy-overview.js").read_text(
        encoding="utf-8"
    )
    theme = (SOURCE.parent / "themes" / "sense-overview.css").read_text(
        encoding="utf-8"
    )
    for marker in (
        'aria-label="Sense Energy Overview"',
        'role="status"',
        'aria-live="polite"',
        "data-piphi-interaction-target",
    ):
        assert marker in source
    for marker in (
        ':root[data-piphi-color-scheme="dark"]',
        "button:focus-visible",
        "@container",
        "@media (prefers-reduced-motion: reduce)",
        "@media (forced-colors: active)",
    ):
        assert marker in theme
    assert 'aria-label="View Sense connection details" hidden' in source
    assert "connection.hidden = connected" in source
    assert theme.count("min-height: 2.75rem") >= 4
    assert "background: #fff" not in theme
    assert ".today-panel { border-top:" in theme
    assert "--sense-orange: #b9381b" in theme
