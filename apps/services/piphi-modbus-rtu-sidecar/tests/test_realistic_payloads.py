from __future__ import annotations

import json
from pathlib import Path

import pytest

from piphi_modbus_rtu_sidecar.profile import decode_point, encode_point
from piphi_modbus_rtu_sidecar.schemas import RegisterProfile


FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "realistic-device-payloads.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["id"])
def test_realistic_device_payload(case: dict) -> None:
    profile = RegisterProfile.model_validate(
        {
            "id": case["id"],
            "name": case["id"].replace("_", " ").title(),
            "unit_id": 1,
            "address": 10,
            **case["point"],
        }
    )
    value = decode_point(profile, case["payload"])
    if isinstance(case["expected"], float):
        assert value == pytest.approx(case["expected"], rel=1e-6)
    else:
        assert value == case["expected"]
    if "write_value" in case:
        assert encode_point(profile, case["write_value"]) == case["expected_write_payload"]


def test_fixture_sources_are_explicit_and_every_case_is_attributed() -> None:
    assert FIXTURE["schema_version"] == "piphi.modbus.fixture.v1"
    assert FIXTURE["sources"]["home_assistant"]["license"] == "Apache-2.0"
    assert all(case["source"] in FIXTURE["sources"] for case in FIXTURE["cases"])
