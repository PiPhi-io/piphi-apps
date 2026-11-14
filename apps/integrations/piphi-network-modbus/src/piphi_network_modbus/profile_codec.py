from __future__ import annotations

import math
import struct
import hashlib
import json
from typing import Any

from .schemas import PointProfile


BYTE_INDEXES = {
    "ABCD": (0, 1, 2, 3),
    "BADC": (1, 0, 3, 2),
    "CDAB": (2, 3, 0, 1),
    "DCBA": (3, 2, 1, 0),
}


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


def decode_point(point: PointProfile, values: list[int | bool]) -> bool | float:
    if point.data_type == "bool":
        if len(values) != 1 or type(values[0]) is not bool:
            raise ValueError("invalid_point_width")
        return values[0]
    if len(values) != point.width or any(type(value) is not int for value in values):
        raise ValueError("invalid_point_width")
    raw = b"".join(int(value).to_bytes(2, "big") for value in values)
    if point.width == 2:
        raw = bytes(raw[index] for index in BYTE_INDEXES[point.byte_order])
    if point.data_type == "uint16":
        decoded: int | float = int.from_bytes(raw, "big")
    elif point.data_type == "int16":
        decoded = int.from_bytes(raw, "big", signed=True)
    elif point.data_type == "uint32":
        decoded = int.from_bytes(raw, "big")
    elif point.data_type == "int32":
        decoded = int.from_bytes(raw, "big", signed=True)
    else:
        decoded = struct.unpack(">f", raw)[0]
        if not math.isfinite(decoded):
            raise ValueError("non_finite_point_value")
    result = float(decoded) * point.scale + point.offset
    if point.minimum is not None and result < point.minimum:
        raise ValueError("point_value_below_minimum")
    if point.maximum is not None and result > point.maximum:
        raise ValueError("point_value_above_maximum")
    return result


def encode_point(point: PointProfile, value: Any) -> list[int | bool]:
    if not point.writable:
        raise ValueError("point_is_read_only")
    if point.data_type == "bool":
        if type(value) is not bool:
            raise ValueError("boolean_value_required")
        return [value]
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ValueError("finite_numeric_value_required")
    numeric = float(value)
    if point.minimum is not None and numeric < point.minimum:
        raise ValueError("point_value_below_minimum")
    if point.maximum is not None and numeric > point.maximum:
        raise ValueError("point_value_above_maximum")
    raw_value = (numeric - point.offset) / point.scale
    if point.data_type != "float32" and not raw_value.is_integer():
        raise ValueError("point_value_not_representable")
    try:
        if point.data_type == "uint16":
            raw = int(raw_value).to_bytes(2, "big", signed=False)
        elif point.data_type == "int16":
            raw = int(raw_value).to_bytes(2, "big", signed=True)
        elif point.data_type == "uint32":
            raw = int(raw_value).to_bytes(4, "big", signed=False)
        elif point.data_type == "int32":
            raw = int(raw_value).to_bytes(4, "big", signed=True)
        else:
            raw = struct.pack(">f", raw_value)
    except (OverflowError, struct.error) as exc:
        raise ValueError("point_value_not_representable") from exc
    if point.width == 2:
        inverse = [0, 0, 0, 0]
        for output_index, input_index in enumerate(BYTE_INDEXES[point.byte_order]):
            inverse[input_index] = output_index
        raw = bytes(raw[index] for index in inverse)
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
        "unit": point.unit,
        "writable": point.writable,
        "minimum": point.minimum,
        "maximum": point.maximum,
    }
