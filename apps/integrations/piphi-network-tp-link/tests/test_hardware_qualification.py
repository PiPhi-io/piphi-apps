from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piphi_network_tp_link.lib.qualification import load_local_env, qualify_read_only

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.hardware
def test_physical_device_read_only_qualification() -> None:
    settings = load_local_env(ROOT / ".qualification.env")
    if settings.get("PIPHI_TP_LINK_RUN_HARDWARE") != "1":
        pytest.skip("physical TP-Link qualification is not enabled")
    report = asyncio.run(
        qualify_read_only(
            host=settings["PIPHI_TP_LINK_QUALIFICATION_HOST"],
            username=settings.get("PIPHI_TP_LINK_QUALIFICATION_USERNAME") or None,
            password=settings.get("PIPHI_TP_LINK_QUALIFICATION_PASSWORD") or None,
            samples=int(settings.get("PIPHI_TP_LINK_QUALIFICATION_SAMPLES", "3")),
        )
    )
    expected_model = settings.get("PIPHI_TP_LINK_EXPECTED_MODEL", "").strip()
    if expected_model:
        assert report["device"]["model"] == expected_model
    assert report["qualification"] == {
        "connectivity": "observed",
        "identity_stability": "observed",
        "capability_stability": "observed",
        "telemetry_accuracy": "not_verified",
        "writes": "not_exercised",
    }
