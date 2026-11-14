from __future__ import annotations

import asyncio
import struct
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from .schemas import DeviceConfig, RegisterProfile

T = TypeVar("T")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def frame_with_crc(payload: bytes) -> bytes:
    return payload + struct.pack("<H", crc16(payload))


def validate_rtu_response(frame: bytes, *, unit_id: int, function: int) -> bytes:
    if len(frame) < 5 or crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise ValueError("invalid_modbus_crc")
    if frame[0] != unit_id:
        raise ValueError("unexpected_modbus_unit")
    if frame[1] == function | 0x80:
        raise ValueError(f"modbus_exception_{frame[2]}")
    if frame[1] != function:
        raise ValueError("unexpected_modbus_function")
    return frame[2:-2]


class BoundedQueue:
    def __init__(self, capacity: int = 100) -> None:
        if not 1 <= capacity <= 1000:
            raise ValueError("queue capacity must be between 1 and 1000")
        self.capacity = capacity
        self.pending = 0
        self._lock = asyncio.Lock()

    async def submit(self, operation: Callable[[], Awaitable[T]]) -> T:
        if self.pending >= self.capacity:
            raise RuntimeError("command_queue_saturated")
        self.pending += 1
        try:
            async with self._lock:
                return await operation()
        finally:
            self.pending -= 1


@dataclass(frozen=True)
class ReplayPage:
    events: list[dict[str, Any]]
    next_cursor: int
    first_sequence: int
    latest_sequence: int
    stream_id: str
    gap: bool
    dropped: int


class EventBuffer:
    def __init__(self, capacity: int = 1000) -> None:
        if not 10 <= capacity <= 10000:
            raise ValueError("event capacity must be between 10 and 10000")
        self.capacity = capacity
        self.stream_id = str(uuid.uuid4())
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._next_sequence = 1
        self.dropped = 0

    def append(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if len(self._events) == self.capacity:
            self.dropped += 1
        event = {
            "schema_version": "piphi.modbus.event.v1",
            "sequence": self._next_sequence,
            "occurred_at": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "payload": sanitize(payload),
        }
        self._next_sequence += 1
        self._events.append(event)
        return event

    def read(self, *, after: int = 0, limit: int = 100) -> ReplayPage:
        bounded = max(1, min(500, int(limit)))
        first = self._events[0]["sequence"] if self._events else self._next_sequence
        events = [event for event in self._events if event["sequence"] > after][:bounded]
        return ReplayPage(
            events=events,
            next_cursor=events[-1]["sequence"] if events else after,
            first_sequence=first,
            latest_sequence=self._next_sequence - 1,
            stream_id=self.stream_id,
            gap=after > 0 and after < first - 1,
            dropped=self.dropped,
        )


SENSITIVE = ("token", "secret", "password", "credential", "raw_frame", "serial_port")


def sanitize(value: Any, *, key: str = "", depth: int = 0) -> Any:
    if any(part in key.lower() for part in SENSITIVE):
        return "[redacted]"
    if depth > 5:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k): sanitize(v, key=str(k), depth=depth + 1) for k, v in list(value.items())[:100]}
    if isinstance(value, list):
        return [sanitize(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, bytes):
        return f"[binary:{len(value)}]"
    if isinstance(value, str) and len(value) > 4096:
        return value[:4096] + "[truncated]"
    return value


FUNCTION_BY_AREA = {
    "coil": 1,
    "discrete_input": 2,
    "holding_register": 3,
    "input_register": 4,
}


class SerialRTUSession:
    """Exclusive, bounded Modbus RTU owner for one configured serial bus."""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.queue = BoundedQueue(config.queue_capacity)
        self._serial: Any | None = None

    async def open(self) -> None:
        await asyncio.to_thread(self._open_sync)

    def _open_sync(self) -> None:
        import serial

        self._serial = serial.Serial(
            port=self.config.serial_port,
            baudrate=self.config.baud_rate,
            bytesize=self.config.data_bits,
            parity=self.config.parity,
            stopbits=self.config.stop_bits,
            timeout=self.config.response_timeout_seconds,
            write_timeout=self.config.response_timeout_seconds,
            exclusive=True,
        )

    async def close(self) -> None:
        serial_port, self._serial = self._serial, None
        if serial_port is not None:
            await asyncio.to_thread(serial_port.close)

    async def read(self, point: RegisterProfile) -> list[int | bool]:
        async def operation() -> list[int | bool]:
            return await asyncio.to_thread(self._read_sync, point)

        return await self.queue.submit(operation)

    def _read_sync(self, point: RegisterProfile) -> list[int | bool]:
        function = FUNCTION_BY_AREA[point.area]
        payload = struct.pack(">BBHH", point.unit_id, function, point.address, point.width)
        response = self._exchange_sync(frame_with_crc(payload), point.unit_id, function)
        if not response:
            raise ValueError("empty_modbus_response")
        byte_count = response[0]
        body = response[1:]
        if byte_count != len(body):
            raise ValueError("invalid_modbus_byte_count")
        if point.area in {"coil", "discrete_input"}:
            if byte_count != 1:
                raise ValueError("invalid_modbus_bit_response")
            return [bool(body[0] & 1)]
        if byte_count != point.width * 2:
            raise ValueError("invalid_modbus_register_response")
        return [int.from_bytes(body[index : index + 2], "big") for index in range(0, len(body), 2)]

    async def write(self, point: RegisterProfile, values: list[int | bool]) -> None:
        async def operation() -> None:
            await asyncio.to_thread(self._write_sync, point, values)

        await self.queue.submit(operation)

    def _write_sync(self, point: RegisterProfile, values: list[int | bool]) -> None:
        if point.unit_id == 0 or not point.writable:
            raise ValueError("write_not_allowed")
        if point.area == "coil" and len(values) == 1 and type(values[0]) is bool:
            encoded = 0xFF00 if values[0] else 0
            function = 5
            request_pdu = struct.pack(">BHH", function, point.address, encoded)
        elif point.area == "holding_register" and len(values) == 1 and type(values[0]) is int:
            function = 6
            request_pdu = struct.pack(">BHH", function, point.address, values[0])
        elif point.area == "holding_register" and len(values) == point.width:
            function = 16
            words = b"".join(int(value).to_bytes(2, "big") for value in values)
            request_pdu = struct.pack(">BHHB", function, point.address, len(values), len(words)) + words
        else:
            raise ValueError("unsupported_profile_write")
        request = frame_with_crc(bytes([point.unit_id]) + request_pdu)
        response = self._exchange_sync(request, point.unit_id, function)
        expected = request_pdu[1:5]
        if response != expected:
            raise ValueError("modbus_write_confirmation_mismatch")

    def _exchange_sync(self, request: bytes, unit_id: int, function: int) -> bytes:
        serial_port = self._serial
        if serial_port is None or not serial_port.is_open:
            raise ConnectionError("serial_port_not_open")
        serial_port.reset_input_buffer()
        serial_port.write(request)
        serial_port.flush()
        header = serial_port.read(3)
        if len(header) != 3:
            raise TimeoutError("modbus_response_timeout")
        if header[1] & 0x80:
            tail = serial_port.read(2)
        elif header[1] in {1, 2, 3, 4}:
            tail = serial_port.read(header[2] + 2)
        else:
            tail = serial_port.read(5)
        frame = header + tail
        return validate_rtu_response(frame, unit_id=unit_id, function=function)
