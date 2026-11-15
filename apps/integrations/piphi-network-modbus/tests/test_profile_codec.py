from __future__ import annotations

import pytest
from pydantic import ValidationError

from piphi_network_modbus.profile_codec import decode_point, encode_point
from piphi_network_modbus.schemas import PointProfile


def point(**overrides) -> PointProfile:
    return PointProfile.model_validate(
        {
            "id": "value",
            "name": "Value",
            "unit_id": 1,
            "address": 0,
            "writable": True,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("byte_order", "words"),
    [
        ("ABCD", [0x0123, 0x4567, 0x89AB, 0xCDEF]),
        ("BADC", [0x2301, 0x6745, 0xAB89, 0xEFCD]),
        ("CDAB", [0xCDEF, 0x89AB, 0x4567, 0x0123]),
        ("DCBA", [0xEFCD, 0xAB89, 0x6745, 0x2301]),
    ],
)
def test_uint64_golden_vectors_are_exact(byte_order: str, words: list[int]) -> None:
    profile = point(data_type="uint64", byte_order=byte_order)
    expected = 0x0123456789ABCDEF
    assert decode_point(profile, words) == expected
    assert encode_point(profile, expected) == words


def test_signed_64_and_float64_round_trip() -> None:
    signed = point(data_type="int64", byte_order="DCBA")
    floating = point(data_type="float64", byte_order="CDAB")
    assert decode_point(signed, encode_point(signed, -(2**63))) == -(2**63)
    assert decode_point(floating, encode_point(floating, 1.5)) == 1.5


@pytest.mark.parametrize(
    ("byte_order", "words"),
    [
        ("ABCD", [0x4142, 0x4344, 0x4546, 0x4748]),
        ("BADC", [0x4241, 0x4443, 0x4645, 0x4847]),
        ("CDAB", [0x4748, 0x4546, 0x4344, 0x4142]),
        ("DCBA", [0x4847, 0x4645, 0x4443, 0x4241]),
    ],
)
def test_fixed_string_golden_vectors(byte_order: str, words: list[int]) -> None:
    profile = point(data_type="string", string_length=8, byte_order=byte_order)
    assert decode_point(profile, words) == "ABCDEFGH"
    assert encode_point(profile, "ABCDEFGH") == words


def test_fixed_string_padding_utf8_and_limits() -> None:
    profile = point(data_type="string", string_length=5, string_encoding="utf-8")
    assert encode_point(profile, "é") == [0xC3A9, 0x0000, 0x0000]
    assert decode_point(profile, [0xC3A9, 0x0000, 0x0000]) == "é"
    with pytest.raises(ValueError, match="too_long"):
        encode_point(profile, "abcdef")


def test_string_profile_options_are_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requires string_length"):
        point(data_type="string")
    with pytest.raises(ValidationError, match="does not support scale"):
        point(data_type="string", string_length=4, scale=2)
    with pytest.raises(ValidationError, match="only valid for string"):
        point(data_type="uint16", string_length=4)


def test_reviewed_enum_labels_round_trip() -> None:
    profile = point(
        data_type="uint16",
        enum_values={"off": 0, "heat": 2, "cool": 3},
    )
    assert decode_point(profile, [2]) == "heat"
    assert encode_point(profile, "cool") == [3]
    with pytest.raises(ValueError, match="unknown_enum_value"):
        decode_point(profile, [1])
    with pytest.raises(ValueError, match="unknown_enum_label"):
        encode_point(profile, "auto")


def test_read_only_bitfield_extracts_declared_bits() -> None:
    profile = point(data_type="uint16", writable=False, bit_mask=0b00111000)
    assert decode_point(profile, [0b10101000]) == 5
    with pytest.raises(ValidationError, match="read-only"):
        point(data_type="uint16", writable=True, bit_mask=1)
