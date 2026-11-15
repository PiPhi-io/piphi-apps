from __future__ import annotations

import math
import struct
import hashlib
import json
from typing import Any

from .schemas import PointProfile


INTEGER_TYPES = {"uint16", "int16", "uint32", "int32", "uint64", "int64"}
SIGNED_TYPES = {"int16", "int32", "int64"}
FLOAT_FORMATS = {"float32": ">f", "float64": ">d"}


def _ordered_bytes(raw: bytes, byte_order: str) -> bytes:
    words = [raw[index : index + 2] for index in range(0, len(raw), 2)]
    if byte_order in {"BADC", "DCBA"}:
        words = [word[::-1] for word in words]
    if byte_order in {"CDAB", "DCBA"}:
        words.reverse()
    return b"".join(words)


def profile_hash(
    *, profile_id: str, profile_version: str, profile_provenance: str, points: list[PointProfile]
) -> str:
    document = {
        "id": profile_id,
        "version": profile_version,
        "provenance": profile_provenance,
        "points": [point.model_dump(mode="json") for point in points],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def decode_point(point: PointProfile, values: list[int | bool]) -> bool | int | float | str:
    if point.data_type == "bool":
        if len(values) != 1 or type(values[0]) is not bool:
            raise ValueError("invalid_point_width")
        return values[0]
    if len(values) != point.width or any(type(value) is not int for value in values):
        raise ValueError("invalid_point_width")
    raw = b"".join(int(value).to_bytes(2, "big") for value in values)
    raw = _ordered_bytes(raw, point.byte_order)
    if point.data_type == "string":
        encoded = raw[: point.string_length].split(b"\0", 1)[0]
        try:
            return encoded.decode(point.string_encoding)
        except UnicodeDecodeError as exc:
            raise ValueError("invalid_string_encoding") from exc
    if point.data_type in INTEGER_TYPES:
        decoded: int | float = int.from_bytes(
            raw, "big", signed=point.data_type in SIGNED_TYPES
        )
    else:
        decoded = struct.unpack(FLOAT_FORMATS[point.data_type], raw)[0]
        if not math.isfinite(decoded):
            raise ValueError("non_finite_point_value")
    if point.bit_mask is not None:
        shift = (point.bit_mask & -point.bit_mask).bit_length() - 1
        return (int(decoded) & point.bit_mask) >> shift
    result: int | float = (
        decoded
        if point.scale == 1 and point.offset == 0
        else float(decoded) * point.scale + point.offset
    )
    if point.minimum is not None and result < point.minimum:
        raise ValueError("point_value_below_minimum")
    if point.maximum is not None and result > point.maximum:
        raise ValueError("point_value_above_maximum")
    if point.enum_values is not None:
        label = next(
            (label for label, mapped in point.enum_values.items() if mapped == result),
            None,
        )
        if label is None:
            raise ValueError("unknown_enum_value")
        return label
    return result


def encode_point(point: PointProfile, value: Any) -> list[int | bool]:
    if not point.writable:
        raise ValueError("point_is_read_only")
    if point.data_type == "bool":
        if type(value) is not bool:
            raise ValueError("boolean_value_required")
        return [value]
    if point.data_type == "string":
        if not isinstance(value, str):
            raise ValueError("string_value_required")
        try:
            encoded = value.encode(point.string_encoding)
        except UnicodeEncodeError as exc:
            raise ValueError("invalid_string_encoding") from exc
        if len(encoded) > (point.string_length or 0):
            raise ValueError("string_value_too_long")
        raw = encoded.ljust(point.width * 2, b"\0")
        raw = _ordered_bytes(raw, point.byte_order)
        return [
            int.from_bytes(raw[index : index + 2], "big")
            for index in range(0, len(raw), 2)
        ]
    if point.enum_values is not None:
        if not isinstance(value, str) or value not in point.enum_values:
            raise ValueError("unknown_enum_label")
        value = point.enum_values[value]
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError("finite_numeric_value_required")
    if point.minimum is not None and value < point.minimum:
        raise ValueError("point_value_below_minimum")
    if point.maximum is not None and value > point.maximum:
        raise ValueError("point_value_above_maximum")
    if (
        point.data_type in INTEGER_TYPES
        and type(value) is int
        and point.scale == 1
        and point.offset == 0
    ):
        raw_value: int | float = value
    else:
        raw_value = (float(value) - point.offset) / point.scale
    if point.data_type in INTEGER_TYPES and int(raw_value) != raw_value:
        raise ValueError("point_value_not_representable")
    try:
        if point.data_type in INTEGER_TYPES:
            raw = int(raw_value).to_bytes(
                point.width * 2,
                "big",
                signed=point.data_type in SIGNED_TYPES,
            )
        else:
            raw = struct.pack(FLOAT_FORMATS[point.data_type], raw_value)
    except (OverflowError, struct.error) as exc:
        raise ValueError("point_value_not_representable") from exc
    raw = _ordered_bytes(raw, point.byte_order)
    return [
        int.from_bytes(raw[index : index + 2], "big")
        for index in range(0, len(raw), 2)
    ]


def point_metadata(point: PointProfile) -> dict[str, Any]:
    return {
        "id": point.id,
        "name": point.name,
        "unit_id": point.unit_id,
        "area": point.area,
        "address": point.address,
        "width": point.width,
        "data_type": point.data_type,
        "byte_order": point.byte_order,
        "string_length": point.string_length,
        "string_encoding": point.string_encoding,
        "enum_values": point.enum_values,
        "bit_mask": point.bit_mask,
        "unit": point.unit,
        "writable": point.writable,
        "minimum": point.minimum,
        "maximum": point.maximum,
    }
