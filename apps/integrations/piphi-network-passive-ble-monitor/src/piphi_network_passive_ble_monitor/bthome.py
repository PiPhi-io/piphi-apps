"""Decode a deliberately small, read-only subset of unencrypted BTHome v2."""

from __future__ import annotations

from typing import Any

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"

# object id: (name, byte length, signed, scale)
OBJECTS = {
    0x00: ("packet_id", 1, False, 1),
    0x01: ("battery_percent", 1, False, 1),
    0x02: ("temperature_c", 2, True, 0.01),
    0x03: ("humidity_percent", 2, False, 0.01),
    0x2E: ("humidity_percent", 1, False, 1),
    0x45: ("temperature_c", 2, True, 0.1),
}


class UnsupportedAdvertisement(ValueError):
    """Advertisement cannot be represented safely by this decoder."""


def decode_bthome(payload: bytes) -> dict[str, Any]:
    """Decode battery, temperature, and humidity without guessing unknown lengths."""
    if not payload or len(payload) > 255:
        raise UnsupportedAdvertisement("invalid advertisement length")
    info = payload[0]
    if info >> 5 != 2:
        raise UnsupportedAdvertisement("not BTHome v2")
    if info & 0x01:
        raise UnsupportedAdvertisement("encrypted BTHome requires a bind key")
    trigger_based = bool(info & 0x04)
    result: dict[str, Any] = {"trigger_based": trigger_based}
    offset = 1
    previous_id = -1
    while offset < len(payload):
        object_id = payload[offset]
        offset += 1
        if object_id < previous_id:
            raise UnsupportedAdvertisement("out-of-order object ids")
        previous_id = object_id
        definition = OBJECTS.get(object_id)
        if definition is None:
            break  # BTHome specifies stopping at an unrecognized object id.
        name, width, signed, scale = definition
        if len(payload) - offset < width:
            raise UnsupportedAdvertisement("truncated object")
        value = int.from_bytes(payload[offset : offset + width], "little", signed=signed)
        offset += width
        if name != "packet_id":
            result[name] = round(value * scale, 2)
    if len(result) == 1:
        raise UnsupportedAdvertisement("no supported measurements")
    if not 0 <= result.get("battery_percent", 50) <= 100:
        raise UnsupportedAdvertisement("invalid battery")
    if not 0 <= result.get("humidity_percent", 50) <= 100:
        raise UnsupportedAdvertisement("invalid humidity")
    return result


def decode_service_data(service_data: dict[str, bytes]) -> dict[str, Any] | None:
    for uuid, payload in service_data.items():
        if uuid.lower() in {BTHOME_UUID, "fcd2", "0000fcd2"}:
            return decode_bthome(payload)
    return None
