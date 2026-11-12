"""Read two documented SUN2000 inverter metrics over local Modbus TCP."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

MBAP = struct.Struct(">HHHB")
LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")


@dataclass(frozen=True)
class InverterReading:
    active_power_w: int
    daily_yield_kwh: float


def local_endpoint(host: str) -> tuple[str, int]:
    raw = host.strip()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("SUN2000 host must be a local hostname or IP address")
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
            raise ValueError("SUN2000 host must be local") from None
    else:
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise ValueError("SUN2000 host must use a local IP")
    return name, port


async def read_sun2000(host: str, unit_id: int = 1) -> InverterReading:
    """Only use function 03 for active power (32080) and daily yield (32114)."""
    if type(unit_id) is not int or not 0 <= unit_id <= 247:
        raise ValueError("Modbus unit ID must be 0–247")
    name, port = local_endpoint(host)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(name, port), 5)
    try:
        active = await _read_two_registers(reader, writer, unit_id, 32080, 1)
        daily = await _read_two_registers(reader, writer, unit_id, 32114, 2)
        return InverterReading(
            active_power_w=struct.unpack(">i", active)[0],
            daily_yield_kwh=struct.unpack(">I", daily)[0] / 100,
        )
    finally:
        writer.close()
        with suppress(OSError, TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), 2)


async def _read_two_registers(
    reader, writer, unit_id: int, address: int, transaction: int
) -> bytes:
    writer.write(
        MBAP.pack(transaction, 0, 6, unit_id) + struct.pack(">BHH", 3, address, 2)
    )
    await asyncio.wait_for(writer.drain(), 5)
    header = await asyncio.wait_for(reader.readexactly(MBAP.size), 5)
    reply_transaction, protocol, length, reply_unit = MBAP.unpack(header)
    if (reply_transaction, protocol, reply_unit) != (
        transaction,
        0,
        unit_id,
    ) or not 2 <= length <= 7:
        raise ValueError("Invalid SUN2000 Modbus response header")
    pdu = await asyncio.wait_for(reader.readexactly(length - 1), 5)
    if len(pdu) == 2 and pdu[0] == 0x83:
        raise ValueError(f"SUN2000 rejected register read (exception {pdu[1]})")
    if len(pdu) != 6 or pdu[:2] != bytes([3, 4]):
        raise ValueError("Invalid SUN2000 register response")
    return pdu[2:]
