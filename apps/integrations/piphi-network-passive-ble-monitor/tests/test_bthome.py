from __future__ import annotations

import pytest

from piphi_network_passive_ble_monitor.bthome import (
    BTHOME_UUID,
    UnsupportedAdvertisement,
    decode_bthome,
    decode_service_data,
)


def test_decodes_documented_temperature_and_humidity_sample() -> None:
    assert decode_bthome(bytes.fromhex("4002C40903BF13")) == {
        "trigger_based": False,
        "temperature_c": 25.0,
        "humidity_percent": 50.55,
    }


def test_battery_negative_temperature_and_alternate_object_ids() -> None:
    sample = bytes.fromhex("40016102D8FF2E2D")
    assert decode_bthome(sample) == {
        "trigger_based": False,
        "battery_percent": 97,
        "temperature_c": -0.4,
        "humidity_percent": 45,
    }
    assert decode_bthome(bytes.fromhex("40450F00"))["temperature_c"] == 1.5
    assert decode_service_data({BTHOME_UUID: bytes.fromhex("400161")}) == {
        "trigger_based": False,
        "battery_percent": 97,
    }


@pytest.mark.parametrize(
    "payload",
    ["", "20", "41", "4002C4", "400165", "40016101"],
)
def test_rejects_invalid_or_encrypted_payloads(payload: str) -> None:
    with pytest.raises(UnsupportedAdvertisement):
        decode_bthome(bytes.fromhex(payload))


def test_unknown_object_stops_without_guessing_its_length() -> None:
    assert decode_bthome(bytes.fromhex("400161E0FFFF02C409")) == {
        "trigger_based": False,
        "battery_percent": 97,
    }
