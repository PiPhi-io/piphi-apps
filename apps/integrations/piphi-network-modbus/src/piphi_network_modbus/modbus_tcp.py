"""Bounded Modbus network transports for profile-declared points."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import ssl
import struct
import time
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


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame_with_crc(payload: bytes) -> bytes:
    return payload + struct.pack("<H", crc16(payload))


def validate_rtu_frame(frame: bytes, *, unit_id: int, function: int) -> bytes:
    if len(frame) < 5 or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise ValueError("invalid_modbus_crc")
    if frame[0] != unit_id:
        raise ValueError("unexpected_modbus_unit")
    if frame[1] == function | 0x80:
        raise ValueError(f"modbus_exception_{frame[2]}")
    if frame[1] != function:
        raise ValueError("unexpected_modbus_function")
    return frame[2:-2]


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


def _tcp_endpoint(host: str, *, default_port: int = 502) -> tuple[str, int]:
    raw = host.strip()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("Modbus host must be a local hostname or IP address")
    parsed = urlsplit(f"tcp://{raw}")
    try:
        port = parsed.port if parsed.port is not None else default_port
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
    def __init__(
        self,
        host: str,
        *,
        timeout: float = 1.0,
        inter_message_delay_ms: int = 0,
        transport: str = "tcp",
        tls_ca_certificate: str | None = None,
        tls_server_name: str | None = None,
    ) -> None:
        if transport not in {"tcp", "tls", "udp", "rtu_over_tcp"}:
            raise ValueError("unsupported_modbus_network_transport")
        self.transport = transport
        self.name, self.port = _tcp_endpoint(
            host, default_port=802 if transport == "tls" else 502
        )
        self.timeout = timeout
        self.tls_server_name = tls_server_name or self.name
        self._ssl_context: ssl.SSLContext | None = None
        if transport == "tls":
            if not tls_ca_certificate:
                raise ValueError("tls_ca_certificate_required")
            self._ssl_context = ssl.create_default_context(cafile=tls_ca_certificate)
            self._ssl_context.check_hostname = True
            self._ssl_context.verify_mode = ssl.CERT_REQUIRED
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | Any | None = None
        self._lock = asyncio.Lock()
        self._transaction = 0
        self._point_cache: dict[str, tuple[bool | int | float | str, str]] = {}
        self._inter_message_delay = inter_message_delay_ms / 1000
        self._last_request_at = 0.0
        self._connection_count = 0
        self._retry_count = 0
        self._timeout_count = 0
        self._error_count = 0
        self._unit_health: dict[int, dict[str, Any]] = {}

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
        if self.transport == "udp":
            return
        if self.connected:
            return
        connection = (
            asyncio.open_connection(
                self.name,
                self.port,
                ssl=self._ssl_context,
                server_hostname=self.tls_server_name,
            )
            if self._ssl_context
            else asyncio.open_connection(self.name, self.port)
        )
        self._reader, self._writer = await asyncio.wait_for(connection, self.timeout)
        self._connection_count += 1

    async def _udp_exchange(self, request: bytes) -> bytes:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        class Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport) -> None:
                self.transport = transport
                transport.sendto(request)

            def datagram_received(self, data: bytes, _address) -> None:
                if not future.done():
                    future.set_result(data)

            def error_received(self, exc: Exception) -> None:
                if not future.done():
                    future.set_exception(exc)

        transport, _ = await loop.create_datagram_endpoint(
            Protocol, remote_addr=(self.name, self.port)
        )
        try:
            return await asyncio.wait_for(future, self.timeout)
        finally:
            transport.close()

    async def _rtu_over_tcp_exchange(
        self, writer: Any, reader: asyncio.StreamReader, request: bytes
    ) -> bytes:
        writer.write(request)
        self._last_request_at = time.monotonic()
        await asyncio.wait_for(writer.drain(), self.timeout)
        header = await asyncio.wait_for(reader.readexactly(3), self.timeout)
        if header[1] & 0x80:
            tail_length = 2
        elif header[1] in {1, 2, 3, 4}:
            tail_length = header[2] + 2
        else:
            tail_length = 5
        return header + await asyncio.wait_for(
            reader.readexactly(tail_length), self.timeout
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
                if self.transport != "udp" and (reader is None or writer is None):
                    raise ConnectionError("modbus_tcp_not_connected")
                self._transaction = self._transaction % 0xFFFF + 1
                transaction = self._transaction
                pdu = bytes([function]) + payload
                remaining_delay = self._inter_message_delay - (
                    time.monotonic() - self._last_request_at
                )
                if remaining_delay > 0:
                    await asyncio.sleep(remaining_delay)
                if self.transport == "rtu_over_tcp":
                    assert writer is not None and reader is not None
                    frame = await self._rtu_over_tcp_exchange(
                        writer, reader, frame_with_crc(bytes([unit_id]) + pdu)
                    )
                    return validate_rtu_frame(
                        frame, unit_id=unit_id, function=function
                    )
                request = MBAP.pack(transaction, 0, len(pdu) + 1, unit_id) + pdu
                if self.transport == "udp":
                    self._last_request_at = time.monotonic()
                    datagram = await self._udp_exchange(request)
                    if len(datagram) < MBAP.size:
                        raise ValueError("invalid_modbus_udp_response")
                    header, response = datagram[: MBAP.size], datagram[MBAP.size :]
                else:
                    writer.write(request)
                    self._last_request_at = time.monotonic()
                    await asyncio.wait_for(writer.drain(), self.timeout)
                    header = await asyncio.wait_for(
                        reader.readexactly(MBAP.size), self.timeout
                    )
                    response = b""
                reply_transaction, protocol, length, reply_unit = MBAP.unpack(header)
                if (
                    reply_transaction != transaction
                    or protocol != 0
                    or reply_unit != unit_id
                    or not 2 <= length <= 254
                ):
                    raise ValueError("invalid_modbus_tcp_header")
                if self.transport == "udp":
                    if len(response) != length - 1:
                        raise ValueError("invalid_modbus_udp_length")
                else:
                    response = await asyncio.wait_for(
                        reader.readexactly(length - 1), self.timeout
                    )
                if len(response) == 2 and response[0] == function | 0x80:
                    raise ValueError(f"modbus_exception_{response[1]}")
                if not response or response[0] != function:
                    raise ValueError("unexpected_modbus_function")
                return response[1:]
            except (TimeoutError, OSError, EOFError, asyncio.IncompleteReadError) as exc:
                if isinstance(exc, TimeoutError):
                    self._timeout_count += 1
                else:
                    self._error_count += 1
                await self.close()
                if attempt + 1 >= attempts:
                    raise
                self._retry_count += 1
            except ValueError:
                self._error_count += 1
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
        started_at = time.monotonic()
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
        blocks = plan_read_blocks(points)
        success_count = 0
        failure_count = 0
        poll_unit_health: dict[int, dict[str, Any]] = {}
        for block in blocks:
            unit_health = self._unit_health.setdefault(
                block.unit_id,
                {
                    "unit_id": block.unit_id,
                    "success_count": 0,
                    "failure_count": 0,
                    "consecutive_error_count": 0,
                    "last_success_at": None,
                    "last_error_code": None,
                },
            )
            poll_health = poll_unit_health.setdefault(
                block.unit_id,
                {
                    "success_count": 0,
                    "failure_count": 0,
                    "last_success_at": None,
                    "last_error_code": None,
                },
            )
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
                success_count += 1
                unit_health.update(
                    success_count=int(unit_health["success_count"]) + 1,
                    last_success_at=timestamp,
                )
                poll_health["success_count"] += 1
                poll_health["last_success_at"] = timestamp
            except (TimeoutError, OSError, EOFError, ValueError) as exc:
                last_error = str(exc) or type(exc).__name__
                failure_count += 1
                unit_health.update(
                    failure_count=int(unit_health["failure_count"]) + 1,
                )
                poll_health["failure_count"] += 1
                poll_health["last_error_code"] = last_error
                for point in block.points:
                    results[point.id]["error_code"] = last_error
        for unit_id, poll_health in poll_unit_health.items():
            unit_health = self._unit_health[unit_id]
            if poll_health["failure_count"]:
                unit_health.update(
                    consecutive_error_count=int(unit_health["consecutive_error_count"])
                    + 1,
                    last_error_code=poll_health["last_error_code"],
                )
            else:
                unit_health.update(
                    consecutive_error_count=0,
                    last_error_code=None,
                )
        return {
            "connected": bool(responsive),
            "responsive_unit_ids": sorted(responsive),
            "points": [results[point.id] for point in points],
            "request_count": len(blocks),
            "request_success_count": success_count,
            "request_failure_count": failure_count,
            "poll_duration_ms": round((time.monotonic() - started_at) * 1000, 3),
            "retry_count": self._retry_count,
            "timeout_count": self._timeout_count,
            "error_count": self._error_count,
            "reconnect_count": max(0, self._connection_count - 1),
            "unit_health": [
                dict(self._unit_health[unit_id]) for unit_id in sorted(self._unit_health)
            ],
            "last_error_code": last_error,
        }

    async def write_point(
        self, point: PointProfile, value: Any
    ) -> bool | int | float | str:
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
        if type(value) is bool or isinstance(value, str):
            matches = decoded == value
        elif type(value) is int and type(decoded) is int:
            matches = decoded == value
        else:
            matches = math.isclose(
                float(decoded), float(value), rel_tol=1e-6, abs_tol=1e-6
            )
        if not matches:
            raise ValueError("modbus_write_readback_mismatch")
        return decoded

    async def write_coils(
        self, points: list[PointProfile], values: list[bool]
    ) -> list[bool]:
        if not 2 <= len(points) <= 1968 or len(points) != len(values):
            raise ValueError("invalid_coil_command_quantity")
        if any(
            point.area != "coil" or not point.writable or type(value) is not bool
            for point, value in zip(points, values, strict=True)
        ):
            raise ValueError("invalid_coil_command_binding")
        first = points[0]
        if any(
            point.unit_id != first.unit_id or point.address != first.address + index
            for index, point in enumerate(points)
        ):
            raise ValueError("coil_command_points_not_contiguous")
        packed = bytearray((len(values) + 7) // 8)
        for index, value in enumerate(values):
            if value:
                packed[index // 8] |= 1 << (index % 8)
        async with self._lock:
            response = await self._request_locked(
                first.unit_id,
                15,
                struct.pack(">HHB", first.address, len(values), len(packed))
                + bytes(packed),
                retry_read=False,
            )
            expected = struct.pack(">HH", first.address, len(values))
            if response != expected:
                raise ValueError("modbus_write_confirmation_mismatch")
            readback = await self._read_block_locked(
                ReadBlock(
                    first.unit_id,
                    "coil",
                    first.address,
                    len(points),
                    tuple(points),
                )
            )
        confirmed = [bool(value) for value in readback]
        if confirmed != values:
            raise ValueError("modbus_write_readback_mismatch")
        return confirmed


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
