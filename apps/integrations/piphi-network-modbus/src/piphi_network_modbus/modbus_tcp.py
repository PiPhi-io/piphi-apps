"""A bounded Modbus TCP function-03 read of one configured holding register."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")
MBAP = struct.Struct(">HHHB")


@dataclass(frozen=True)
class HoldingRegister:
    address: int
    value: int


def _tcp_endpoint(host: str) -> tuple[str, int]:
    raw = host.strip()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("Modbus host must be a local hostname or IP address")
    parsed = urlsplit(f"tcp://{raw}")
    try:
        port = parsed.port if parsed.port is not None else 502
    except ValueError as exc:
        raise ValueError("Invalid Modbus TCP port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Modbus TCP port")
    name = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        if (
            not LOCAL_NAME.fullmatch(name)
            or ".." in name
            or not name.endswith((".local", ".lan"))
        ):
            raise ValueError("Modbus host must be local") from None
    else:
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise ValueError("Modbus host must use a local IP")
    return name, port


async def read_holding_register(
    host: str,
    address: int,
    unit_id: int = 1,
) -> HoldingRegister:
    """Read one unsigned 16-bit register; never send a write function code."""
    if type(address) is not int or not 0 <= address <= 65535:
        raise ValueError("Register address must be 0–65535")
    if type(unit_id) is not int or not 1 <= unit_id <= 247:
        raise ValueError("Unit ID must be 1–247")
    name, port = _tcp_endpoint(host)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(name, port), 5)
    try:
        # Transaction 1, protocol 0, length 6: unit + function + address + quantity.
        writer.write(MBAP.pack(1, 0, 6, unit_id) + struct.pack(">BHH", 3, address, 1))
        await asyncio.wait_for(writer.drain(), 5)
        header = await asyncio.wait_for(reader.readexactly(MBAP.size), 5)
        transaction, protocol, length, reply_unit = MBAP.unpack(header)
        if (
            transaction != 1
            or protocol != 0
            or reply_unit != unit_id
            or not 2 <= length <= 5
        ):
            raise ValueError("Invalid Modbus TCP response header")
        pdu = await asyncio.wait_for(reader.readexactly(length - 1), 5)
        if len(pdu) == 2 and pdu[0] == 0x83:
            raise ValueError(f"Modbus device rejected the read (exception {pdu[1]})")
        if len(pdu) != 4 or pdu[0] != 3 or pdu[1] != 2:
            raise ValueError("Invalid Modbus holding-register response")
        return HoldingRegister(address, struct.unpack(">H", pdu[2:])[0])
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()
