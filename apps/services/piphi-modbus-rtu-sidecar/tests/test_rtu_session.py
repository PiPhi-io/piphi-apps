from __future__ import annotations

import asyncio
import os
import pty
import random
import struct
import tty

import pytest

from piphi_modbus_rtu_sidecar.profile import decode_point, encode_point, profile_hash
from piphi_modbus_rtu_sidecar.schemas import DeviceConfig, RegisterProfile
from piphi_modbus_rtu_sidecar.transport import (
    SerialRTUSession,
    crc16,
    frame_ascii,
    frame_with_crc,
    validate_ascii_response,
    validate_rtu_response,
)
from piphi_modbus_rtu_sidecar import transport


def point(**updates) -> RegisterProfile:
    values = {
        "id": "temperature",
        "name": "Temperature",
        "unit_id": 7,
        "address": 42,
        "area": "holding_register",
        "data_type": "uint16",
    }
    values.update(updates)
    return RegisterProfile.model_validate(values)


@pytest.mark.parametrize(
    ("data_type", "byte_order", "words", "expected"),
    [
        ("uint16", "ABCD", [0xFFFF], 65535.0),
        ("int16", "ABCD", [0xFFFF], -1.0),
        ("uint32", "ABCD", [0x1234, 0x5678], float(0x12345678)),
        ("uint32", "CDAB", [0x5678, 0x1234], float(0x12345678)),
        ("uint32", "BADC", [0x3412, 0x7856], float(0x12345678)),
        ("uint32", "DCBA", [0x7856, 0x3412], float(0x12345678)),
        ("float32", "ABCD", [0x3FC0, 0x0000], 1.5),
    ],
)
def test_profile_decoding_golden_vectors(
    data_type: str, byte_order: str, words: list[int], expected: float
) -> None:
    profile = point(data_type=data_type, byte_order=byte_order)
    assert decode_point(profile, words) == expected


def test_profile_scaling_bounds_and_round_trip_write() -> None:
    profile = point(
        data_type="int16",
        scale=0.1,
        offset=-10,
        minimum=-10,
        maximum=100,
        writable=True,
    )
    assert decode_point(profile, [123]) == pytest.approx(2.3)
    encoded = encode_point(profile, 2.3)
    assert encoded == [123]
    assert decode_point(profile, encoded) == pytest.approx(2.3)
    with pytest.raises(ValueError, match="above_maximum"):
        encode_point(profile, 101)


@pytest.mark.parametrize(
    ("data_type", "byte_order", "value"),
    [
        ("uint64", "ABCD", 0x0123456789ABCDEF),
        ("uint64", "BADC", 0x0123456789ABCDEF),
        ("int64", "CDAB", -(2**63)),
        ("float64", "DCBA", 1.5),
    ],
)
def test_extended_numeric_types_round_trip(
    data_type: str, byte_order: str, value: int | float
) -> None:
    profile = point(data_type=data_type, byte_order=byte_order, writable=True)
    assert decode_point(profile, encode_point(profile, value)) == value


def test_float16_and_bounded_value_policies() -> None:
    half = point(data_type="float16", writable=True)
    assert encode_point(half, 1.5) == [0x3E00]
    assert decode_point(half, [0x3E00]) == 1.5

    profile = point(
        data_type="int16",
        writable=True,
        precision=1,
        minimum=-5,
        maximum=5,
        out_of_range_policy="clamp",
        invalid_raw_values=[[0x7FFF]],
    )
    assert decode_point(profile, [70]) == 5
    assert decode_point(profile, [0xFFBA]) == -5
    with pytest.raises(ValueError, match="invalid_profile_raw_value"):
        decode_point(profile, [0x7FFF])
    sentinel = point(
        data_type="uint16", writable=True, invalid_raw_values=[[0xFFFF]]
    )
    with pytest.raises(ValueError, match="encodes_invalid"):
        encode_point(sentinel, 0xFFFF)


@pytest.mark.parametrize("byte_order", ["ABCD", "BADC", "CDAB", "DCBA"])
def test_fixed_strings_round_trip_for_every_order(byte_order: str) -> None:
    profile = point(
        data_type="string",
        string_length=8,
        byte_order=byte_order,
        writable=True,
    )
    assert decode_point(profile, encode_point(profile, "ABCDEFGH")) == "ABCDEFGH"


def test_reviewed_enum_and_bitfield_decoding() -> None:
    enum = point(
        data_type="uint16",
        enum_values={"idle": 0, "running": 4},
        writable=True,
    )
    bitfield = point(data_type="uint16", bit_mask=0x00F0)
    assert decode_point(enum, [4]) == "running"
    assert encode_point(enum, "idle") == [0]
    assert decode_point(bitfield, [0x00B0]) == 11


def test_profile_hash_is_stable_and_semantic() -> None:
    config = DeviceConfig(
        id="bus",
        serial_port="/dev/serial/by-id/example",
        profile_id="meter.acme",
        profile_version="1.0.0",
        registers=[point()],
    )
    first = profile_hash(config)
    assert first == profile_hash(config.model_copy(deep=True))
    changed = config.model_copy(
        update={"registers": [point(address=43)]},
        deep=True,
    )
    assert profile_hash(changed) != first
    assert profile_hash(config.model_copy(update={"serial_mode": "ascii"})) != first


@pytest.mark.anyio
async def test_real_pty_rtu_read_and_write() -> None:
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    slave_name = os.ttyname(slave_fd)
    profile = point(writable=True)
    config = DeviceConfig(id="pty-bus", serial_port=slave_name, registers=[profile])
    session = SerialRTUSession(config)
    await session.open()

    async def simulator() -> None:
        read_request = await asyncio.to_thread(os.read, master_fd, 256)
        assert validate_rtu_response(
            frame_with_crc(read_request[:-2]), unit_id=7, function=3
        ) == struct.pack(">HH", 42, 1)
        os.write(master_fd, frame_with_crc(bytes.fromhex("0703021234")))

        write_request = await asyncio.to_thread(os.read, master_fd, 256)
        assert write_request[0:2] == bytes([7, 6])
        os.write(master_fd, write_request)

        confirm_request = await asyncio.to_thread(os.read, master_fd, 256)
        assert confirm_request[0:2] == bytes([7, 3])
        os.write(master_fd, frame_with_crc(bytes.fromhex("070302002A")))

    task = asyncio.create_task(simulator())
    try:
        assert await session.read(profile) == [0x1234]
        await session.write(profile, [42])
        assert await session.read(profile) == [42]
        await task
    finally:
        await session.close()
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("area", "function", "response_data", "expected"),
    [
        ("coil", 1, b"\x01\x01", [True]),
        ("discrete_input", 2, b"\x01\x00", [False]),
        ("holding_register", 3, b"\x02\x12\x34", [0x1234]),
        ("input_register", 4, b"\x02\x56\x78", [0x5678]),
    ],
    ids=("fc01-coil", "fc02-discrete", "fc03-holding", "fc04-input"),
)
async def test_real_pty_read_function_matrix(
    area: str, function: int, response_data: bytes, expected: list[int | bool]
) -> None:
    """Every advertised read function crosses the real serial/CRC boundary."""
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    profile = point(
        area=area,
        data_type="bool" if area in {"coil", "discrete_input"} else "uint16",
    )
    session = SerialRTUSession(
        DeviceConfig(
            id=f"read-fc{function:02d}",
            serial_port=os.ttyname(slave_fd),
            registers=[profile],
        )
    )
    await session.open()

    async def simulator() -> None:
        request = await asyncio.to_thread(os.read, master_fd, 256)
        assert crc16(request) == 0
        assert request[:2] == bytes([7, function])
        assert request[2:6] == struct.pack(">HH", 42, 1)
        os.write(master_fd, frame_with_crc(bytes([7, function]) + response_data))

    task = asyncio.create_task(simulator())
    try:
        assert await session.read(profile) == expected
        await task
    finally:
        await session.close()
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("profile", "values", "function"),
    [
        (point(area="coil", data_type="bool", writable=True), [True], 5),
        (point(writable=True), [99], 6),
        (point(data_type="uint32", writable=True), [0x1234, 0x5678], 16),
    ],
    ids=("fc05-single-coil", "fc06-single-register", "fc16-multiple-registers"),
)
async def test_real_pty_write_function_matrix(
    profile: RegisterProfile, values: list[int | bool], function: int
) -> None:
    """Every profile-bound write function validates its wire confirmation."""
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    session = SerialRTUSession(
        DeviceConfig(
            id=f"write-fc{function:02d}",
            serial_port=os.ttyname(slave_fd),
            registers=[profile],
        )
    )
    await session.open()

    async def simulator() -> None:
        request = await asyncio.to_thread(os.read, master_fd, 256)
        assert crc16(request) == 0
        assert request[:2] == bytes([7, function])
        response = request[:-2] if function in {5, 6} else request[:6]
        os.write(master_fd, frame_with_crc(response))

    task = asyncio.create_task(simulator())
    try:
        await session.write(profile, values)
        await task
    finally:
        await session.close()
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.anyio
async def test_real_pty_fc15_multiple_coil_write() -> None:
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    slave_name = os.ttyname(slave_fd)
    points = [
        point(
            id=f"relay_{index}",
            name=f"Relay {index}",
            area="coil",
            address=index,
            data_type="bool",
            writable=True,
        )
        for index in range(3)
    ]
    session = SerialRTUSession(
        DeviceConfig(id="coil-bus", serial_port=slave_name, registers=points)
    )
    await session.open()

    async def simulator() -> None:
        request = await asyncio.to_thread(os.read, master_fd, 256)
        assert request[:7] == bytes([7, 15, 0, 0, 0, 3, 1])
        assert request[7] == 0b00000101
        os.write(master_fd, frame_with_crc(bytes.fromhex("070F00000003")))

    task = asyncio.create_task(simulator())
    try:
        await session.write_coils(points, [True, False, True])
        await task
    finally:
        await session.close()
        os.close(master_fd)
        os.close(slave_fd)


@pytest.mark.anyio
async def test_real_pty_serial_ascii_read() -> None:
    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    slave_name = os.ttyname(slave_fd)
    profile = point(writable=True)
    session = SerialRTUSession(
        DeviceConfig(
            id="ascii-bus",
            serial_port=slave_name,
            serial_mode="ascii",
            data_bits=7,
            parity="E",
            registers=[profile],
        )
    )
    await session.open()

    async def simulator() -> None:
        request = await asyncio.to_thread(os.read, master_fd, 256)
        assert validate_ascii_response(
            request, unit_id=7, function=3
        ) == struct.pack(">HH", 42, 1)
        os.write(master_fd, frame_ascii(bytes.fromhex("0703021234")))
        write_request = await asyncio.to_thread(os.read, master_fd, 256)
        assert validate_ascii_response(
            write_request, unit_id=7, function=6
        ) == struct.pack(">HH", 42, 99)
        os.write(master_fd, write_request)

    task = asyncio.create_task(simulator())
    try:
        assert await session.read(profile) == [0x1234]
        await session.write(profile, [99])
        await task
    finally:
        await session.close()
        os.close(master_fd)
        os.close(slave_fd)


def test_ascii_lrc_validation_fails_closed() -> None:
    valid = frame_ascii(bytes.fromhex("0703021234"))
    assert validate_ascii_response(valid, unit_id=7, function=3) == bytes.fromhex(
        "021234"
    )
    corrupted = valid[:-4] + b"00\r\n"
    with pytest.raises(ValueError, match="invalid_modbus_lrc"):
        validate_ascii_response(corrupted, unit_id=7, function=3)


def test_serial_frame_parsers_reject_random_input_without_crashing() -> None:
    generator = random.Random(20261115)
    for _ in range(500):
        candidate = bytes(
            generator.randrange(256) for _ in range(generator.randrange(0, 260))
        )
        for parser in (validate_rtu_response, validate_ascii_response):
            try:
                parser(candidate, unit_id=7, function=3)
            except ValueError:
                pass


def test_rtu_exchange_enforces_inter_frame_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = frame_with_crc(bytes.fromhex("0703021234"))

    class FakeSerial:
        is_open = True

        def reset_input_buffer(self) -> None:
            return None

        def write(self, _request: bytes) -> None:
            return None

        def flush(self) -> None:
            return None

        def read(self, size: int) -> bytes:
            return response[:3] if size == 3 else response[3:]

    now = [100.0]
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return now[0]

    def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr(transport.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(transport.time, "sleep", fake_sleep)
    session = SerialRTUSession(
        DeviceConfig(
            id="timing",
            serial_port="/dev/serial/by-id/timing",
            baud_rate=115200,
            registers=[point()],
        )
    )
    session._serial = FakeSerial()
    request = frame_with_crc(bytes.fromhex("0703002A0001"))
    assert session._exchange_sync(request, 7, 3) == bytes.fromhex("021234")
    assert session._exchange_sync(request, 7, 3) == bytes.fromhex("021234")
    assert sleeps == [pytest.approx(0.00175)]
