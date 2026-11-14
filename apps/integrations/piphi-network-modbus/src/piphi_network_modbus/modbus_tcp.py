"""Persistent, bounded Modbus TCP transport for profile-declared points."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from .profile_codec import decode_point, encode_point, point_metadata
from .schemas import PointProfile

LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")
MBAP = struct.Struct(">HHHB")
FUNCTION_BY_AREA = {
    "coil": 1,
    "discrete_input": 2,
    "holding_register": 3,
    "input_register": 4,
}
MAX_QUANTITY_BY_AREA = {
    "coil": 2000,
    "discrete_input": 2000,
    "holding_register": 125,
    "input_register": 125,
}


@dataclass(frozen=True)
class HoldingRegister:
    address: int
    value: int


@dataclass(frozen=True)
class ReadBlock:
    unit_id: int
    area: str
    address: int
    quantity: int
    points: tuple[PointProfile, ...]


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


def plan_read_blocks(points: list[PointProfile]) -> list[ReadBlock]:
    blocks: list[ReadBlock] = []
    ordered = sorted(points, key=lambda point: (point.unit_id, point.area, point.address))
    current: list[PointProfile] = []
    for point in ordered:
        if current:
            first = current[0]
            end = current[-1].address + current[-1].width
            quantity = point.address + point.width - first.address
            compatible = (
                point.unit_id == first.unit_id
                and point.area == first.area
                and point.address == end
                and quantity <= MAX_QUANTITY_BY_AREA[first.area]
            )
            if not compatible:
                blocks.append(_make_block(current))
                current = []
        current.append(point)
    if current:
        blocks.append(_make_block(current))
    return blocks


def _make_block(points: list[PointProfile]) -> ReadBlock:
    first = points[0]
    return ReadBlock(
        unit_id=first.unit_id,
        area=first.area,
        address=first.address,
        quantity=points[-1].address + points[-1].width - first.address,
        points=tuple(points),
    )


class ModbusTCPClient:
    def __init__(self, host: str, *, timeout: float = 1.0) -> None:
        self.name, self.port = _tcp_endpoint(host)
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | Any | None = None
        self._lock = asyncio.Lock()
        self._transaction = 0
        self._point_cache: dict[str, tuple[bool | float, str]] = {}

    @property
    def connected(self) -> bool:
        return self._writer is not None and not bool(
            getattr(self._writer, "is_closing", lambda: False)()
        )

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is not None:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def _connect_locked(self) -> None:
        if self.connected:
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.name, self.port), self.timeout
        )

    async def _request_locked(
        self,
        unit_id: int,
        function: int,
        payload: bytes,
        *,
        retry_read: bool,
    ) -> bytes:
        attempts = 2 if retry_read else 1
        for attempt in range(attempts):
            try:
                await self._connect_locked()
                reader, writer = self._reader, self._writer
                if reader is None or writer is None:
                    raise ConnectionError("modbus_tcp_not_connected")
                self._transaction = self._transaction % 0xFFFF + 1
                transaction = self._transaction
                pdu = bytes([function]) + payload
                writer.write(MBAP.pack(transaction, 0, len(pdu) + 1, unit_id) + pdu)
                await asyncio.wait_for(writer.drain(), self.timeout)
                header = await asyncio.wait_for(reader.readexactly(MBAP.size), self.timeout)
                reply_transaction, protocol, length, reply_unit = MBAP.unpack(header)
                if (
                    reply_transaction != transaction
                    or protocol != 0
                    or reply_unit != unit_id
                    or not 2 <= length <= 254
                ):
                    raise ValueError("invalid_modbus_tcp_header")
                response = await asyncio.wait_for(reader.readexactly(length - 1), self.timeout)
                if len(response) == 2 and response[0] == function | 0x80:
                    raise ValueError(f"modbus_exception_{response[1]}")
                if not response or response[0] != function:
                    raise ValueError("unexpected_modbus_function")
                return response[1:]
            except (TimeoutError, OSError, EOFError, asyncio.IncompleteReadError):
                await self.close()
                if attempt + 1 >= attempts:
                    raise
            except ValueError:
                await self.close()
                raise
        raise AssertionError("unreachable")

    async def read_block(self, block: ReadBlock) -> list[int | bool]:
        async with self._lock:
            return await self._read_block_locked(block)

    async def _read_block_locked(self, block: ReadBlock) -> list[int | bool]:
        function = FUNCTION_BY_AREA[block.area]
        response = await self._request_locked(
            block.unit_id,
            function,
            struct.pack(">HH", block.address, block.quantity),
            retry_read=True,
        )
        if not response:
            raise ValueError("empty_modbus_response")
        byte_count, body = response[0], response[1:]
        if byte_count != len(body):
            raise ValueError("invalid_modbus_byte_count")
        if block.area in {"coil", "discrete_input"}:
            expected = (block.quantity + 7) // 8
            if byte_count != expected:
                raise ValueError("invalid_modbus_bit_response")
            return [bool(body[index // 8] & (1 << (index % 8))) for index in range(block.quantity)]
        if byte_count != block.quantity * 2:
            raise ValueError("invalid_modbus_register_response")
        return [
            int.from_bytes(body[index : index + 2], "big")
            for index in range(0, len(body), 2)
        ]

    async def snapshot(self, points: list[PointProfile]) -> dict[str, Any]:
        results: dict[str, dict[str, Any]] = {
            point.id: {
                **point_metadata(point),
                "value": self._point_cache.get(point.id, (None, None))[0],
                "quality": "stale" if point.id in self._point_cache else "unavailable",
                "updated_at": self._point_cache.get(point.id, (None, None))[1],
                "error_code": None,
            }
            for point in points
        }
        responsive: set[int] = set()
        last_error: str | None = None
        for block in plan_read_blocks(points):
            try:
                values = await self.read_block(block)
                timestamp = datetime.now(UTC).isoformat()
                for point in block.points:
                    offset = point.address - block.address
                    raw = values[offset : offset + point.width]
                    decoded = decode_point(point, raw)
                    results[point.id].update(
                        value=decoded,
                        quality="good",
                        updated_at=timestamp,
                    )
                    self._point_cache[point.id] = (decoded, timestamp)
                responsive.add(block.unit_id)
            except (TimeoutError, OSError, EOFError, ValueError) as exc:
                last_error = str(exc) or type(exc).__name__
                for point in block.points:
                    results[point.id]["error_code"] = last_error
        return {
            "connected": bool(responsive),
            "responsive_unit_ids": sorted(responsive),
            "points": [results[point.id] for point in points],
            "request_count": len(plan_read_blocks(points)),
            "last_error_code": last_error,
        }

    async def write_point(self, point: PointProfile, value: Any) -> bool | float:
        values = encode_point(point, value)
        async with self._lock:
            if point.area == "coil" and len(values) == 1 and type(values[0]) is bool:
                encoded = 0xFF00 if values[0] else 0
                response = await self._request_locked(
                    point.unit_id,
                    5,
                    struct.pack(">HH", point.address, encoded),
                    retry_read=False,
                )
                if response != struct.pack(">HH", point.address, encoded):
                    raise ValueError("modbus_write_confirmation_mismatch")
            elif point.area == "holding_register" and len(values) == 1:
                response = await self._request_locked(
                    point.unit_id,
                    6,
                    struct.pack(">HH", point.address, int(values[0])),
                    retry_read=False,
                )
                if response != struct.pack(">HH", point.address, int(values[0])):
                    raise ValueError("modbus_write_confirmation_mismatch")
            elif point.area == "holding_register":
                words = b"".join(int(item).to_bytes(2, "big") for item in values)
                response = await self._request_locked(
                    point.unit_id,
                    16,
                    struct.pack(">HHB", point.address, len(values), len(words)) + words,
                    retry_read=False,
                )
                if response != struct.pack(">HH", point.address, len(values)):
                    raise ValueError("modbus_write_confirmation_mismatch")
            else:
                raise ValueError("unsupported_profile_write")
            readback = await self._read_block_locked(
                ReadBlock(point.unit_id, point.area, point.address, point.width, (point,))
            )
        decoded = decode_point(point, readback)
        matches = (
            decoded is value
            if type(value) is bool
            else math.isclose(float(decoded), float(value), rel_tol=1e-6, abs_tol=1e-6)
        )
        if not matches:
            raise ValueError("modbus_write_readback_mismatch")
        return decoded


async def read_holding_register(
    host: str,
    address: int,
    unit_id: int = 1,
) -> HoldingRegister:
    """Compatibility wrapper for the original single-register TCP configuration."""
    if type(address) is not int or not 0 <= address <= 65535:
        raise ValueError("Register address must be 0–65535")
    if type(unit_id) is not int or not 1 <= unit_id <= 247:
        raise ValueError("Unit ID must be 1–247")
    client = ModbusTCPClient(host, timeout=5)
    try:
        block = ReadBlock(unit_id, "holding_register", address, 1, ())
        try:
            values = await client.read_block(block)
        except ValueError as exc:
            if str(exc).startswith("modbus_exception_"):
                code = str(exc).rsplit("_", 1)[-1]
                raise ValueError(
                    f"Modbus device rejected the read (exception {code})"
                ) from exc
            raise
        return HoldingRegister(address, int(values[0]))
    finally:
        await client.close()
