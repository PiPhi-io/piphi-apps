from __future__ import annotations

import asyncio
import struct

import pytest

from piphi_network_modbus import state
from piphi_network_modbus.modbus_tcp import MBAP, ModbusTCPClient, plan_read_blocks
from piphi_network_modbus.modbus_model import normalize_snapshot
from piphi_network_modbus.schemas import DeviceConfig, PointProfile


class ModbusTCPDevice:
    def __init__(self) -> None:
        self.registers = {0: 0x4366, 1: 0x8000, 2: 123, 10: 7}
        self.coils = {0: False}
        self.requests: list[tuple[int, int, bytes]] = []
        self.connections = 0
        self.disconnect_once = False
        self.fail_functions: set[int] = set()
        self.server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = int(self.server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            while True:
                header = await reader.readexactly(MBAP.size)
                transaction, protocol, length, unit_id = MBAP.unpack(header)
                assert protocol == 0
                pdu = await reader.readexactly(length - 1)
                function, payload = pdu[0], pdu[1:]
                self.requests.append((unit_id, function, payload))
                if self.disconnect_once:
                    self.disconnect_once = False
                    return
                response = self.respond(function, payload)
                writer.write(
                    MBAP.pack(transaction, 0, len(response) + 1, unit_id) + response
                )
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    def respond(self, function: int, payload: bytes) -> bytes:
        if function in self.fail_functions:
            return bytes([function | 0x80, 4])
        if function in {3, 4}:
            address, quantity = struct.unpack(">HH", payload)
            values = b"".join(
                self.registers.get(index, 0).to_bytes(2, "big")
                for index in range(address, address + quantity)
            )
            return bytes([function, len(values)]) + values
        if function in {1, 2}:
            address, quantity = struct.unpack(">HH", payload)
            packed = 0
            for offset in range(quantity):
                if self.coils.get(address + offset, False):
                    packed |= 1 << offset
            body = packed.to_bytes((quantity + 7) // 8, "little")
            return bytes([function, len(body)]) + body
        if function == 5:
            address, encoded = struct.unpack(">HH", payload)
            self.coils[address] = encoded == 0xFF00
            return bytes([function]) + payload
        if function == 6:
            address, value = struct.unpack(">HH", payload)
            self.registers[address] = value
            return bytes([function]) + payload
        if function == 16:
            address, quantity, byte_count = struct.unpack(">HHB", payload[:5])
            assert byte_count == quantity * 2
            for offset in range(quantity):
                start = 5 + offset * 2
                self.registers[address + offset] = int.from_bytes(
                    payload[start : start + 2], "big"
                )
            return bytes([function]) + struct.pack(">HH", address, quantity)
        return bytes([function | 0x80, 1])


def profile_points() -> list[PointProfile]:
    return [
        PointProfile(
            id="voltage",
            name="Voltage",
            unit_id=1,
            area="input_register",
            address=0,
            data_type="float32",
            unit="V",
        ),
        PointProfile(
            id="current",
            name="Current",
            unit_id=1,
            area="input_register",
            address=2,
            data_type="uint16",
            scale=0.1,
            unit="A",
        ),
        PointProfile(
            id="setpoint",
            name="Setpoint",
            unit_id=1,
            address=10,
            data_type="uint16",
            writable=True,
            minimum=0,
            maximum=100,
        ),
        PointProfile(
            id="relay",
            name="Relay",
            unit_id=2,
            area="coil",
            address=0,
            data_type="bool",
            writable=True,
        ),
    ]


def test_planner_batches_only_safe_contiguous_ranges() -> None:
    blocks = plan_read_blocks(profile_points())
    assert [
        (block.unit_id, block.area, block.address, block.quantity)
        for block in blocks
    ] == [
        (1, "holding_register", 10, 1),
        (1, "input_register", 0, 3),
        (2, "coil", 0, 1),
    ]


@pytest.mark.anyio
async def test_tcp_profile_batches_reads_and_reuses_connection() -> None:
    device = ModbusTCPDevice()
    await device.start()
    client = ModbusTCPClient(f"127.0.0.1:{device.port}")
    try:
        snapshot = await client.snapshot(profile_points())
        values = {point["id"]: point["value"] for point in snapshot["points"]}
        assert values == {
            "voltage": pytest.approx(230.5),
            "current": pytest.approx(12.3),
            "setpoint": pytest.approx(7.0),
            "relay": False,
        }
        assert snapshot["request_count"] == 3
        assert snapshot["request_success_count"] == 3
        assert snapshot["request_failure_count"] == 0
        assert snapshot["poll_duration_ms"] >= 0
        assert [unit["unit_id"] for unit in snapshot["unit_health"]] == [1, 2]
        await client.snapshot(profile_points())
        assert device.connections == 1
        assert len(device.requests) == 6
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_tcp_profile_enforces_inter_message_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = ModbusTCPDevice()
    await device.start()
    client = ModbusTCPClient(
        f"127.0.0.1:{device.port}", inter_message_delay_ms=25
    )
    delays: list[float] = []
    original_sleep = asyncio.sleep

    async def record_sleep(delay: float) -> None:
        delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr(
        "piphi_network_modbus.modbus_tcp.asyncio.sleep", record_sleep
    )
    try:
        await client.snapshot(profile_points())
        assert len(delays) == 2
        assert all(0 < delay <= 0.025 for delay in delays)
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_tcp_profile_read_reconnects_once_after_disconnect() -> None:
    device = ModbusTCPDevice()
    device.disconnect_once = True
    await device.start()
    client = ModbusTCPClient(f"127.0.0.1:{device.port}")
    try:
        snapshot = await client.snapshot([profile_points()[2]])
        assert snapshot["connected"] is True
        assert snapshot["points"][0]["value"] == 7
        assert device.connections == 2
        assert snapshot["retry_count"] == 1
        assert snapshot["reconnect_count"] == 1
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_tcp_profile_partial_failure_preserves_stale_values() -> None:
    device = ModbusTCPDevice()
    await device.start()
    client = ModbusTCPClient(f"127.0.0.1:{device.port}")
    try:
        first = await client.snapshot(profile_points())
        assert all(point["quality"] == "good" for point in first["points"])
        device.fail_functions.add(4)
        second = await client.snapshot(profile_points())
        points = {point["id"]: point for point in second["points"]}
        assert points["voltage"]["value"] == pytest.approx(230.5)
        assert points["voltage"]["quality"] == "stale"
        assert points["current"]["quality"] == "stale"
        assert points["setpoint"]["quality"] == "good"
        assert second["connected"] is True
        assert second["last_error_code"] == "modbus_exception_4"
        assert second["request_success_count"] == 2
        assert second["request_failure_count"] == 1
        unit_one = next(item for item in second["unit_health"] if item["unit_id"] == 1)
        assert unit_one["failure_count"] == 1
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_tcp_profile_constrained_writes_have_readback() -> None:
    device = ModbusTCPDevice()
    await device.start()
    client = ModbusTCPClient(f"127.0.0.1:{device.port}")
    points = {point.id: point for point in profile_points()}
    try:
        assert await client.write_point(points["setpoint"], 42) == 42
        assert await client.write_point(points["relay"], True) is True
        assert device.registers[10] == 42
        assert device.coils[0] is True
        assert [request[1] for request in device.requests] == [6, 3, 5, 1]
        with pytest.raises(ValueError, match="above_maximum"):
            await client.write_point(points["setpoint"], 101)
        with pytest.raises(ValueError, match="read_only"):
            await client.write_point(points["voltage"], 230)
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_tcp_extended_types_and_semantic_entities() -> None:
    device = ModbusTCPDevice()
    device.registers.update(
        {
            20: 0x0123,
            21: 0x4567,
            22: 0x89AB,
            23: 0xCDEF,
            24: 0x3FF8,
            25: 0,
            26: 0,
            27: 0,
            28: 0x4142,
            29: 0x4344,
            30: 0,
            31: 2,
            32: 0x00B0,
        }
    )
    points = [
        PointProfile(id="counter", name="Counter", unit_id=1, address=20, data_type="uint64"),
        PointProfile(id="energy", name="Energy", unit_id=1, address=24, data_type="float64"),
        PointProfile(
            id="label",
            name="Label",
            unit_id=1,
            address=28,
            data_type="string",
            string_length=6,
            writable=True,
        ),
        PointProfile(
            id="mode",
            name="Mode",
            unit_id=1,
            address=31,
            data_type="uint16",
            enum_values={"off": 0, "heat": 2, "cool": 3},
            writable=True,
        ),
        PointProfile(
            id="status",
            name="Status",
            unit_id=1,
            address=32,
            data_type="uint16",
            bit_mask=0x00F0,
        ),
    ]
    await device.start()
    client = ModbusTCPClient(f"127.0.0.1:{device.port}")
    try:
        snapshot = await client.snapshot(points)
        values = {item["id"]: item["value"] for item in snapshot["points"]}
        assert values == {
            "counter": 0x0123456789ABCDEF,
            "energy": 1.5,
            "label": "ABCD",
            "mode": "heat",
            "status": 11,
        }
        entities = {item["point_id"]: item for item in normalize_snapshot(snapshot, config_id="extended")}
        assert entities["mode"]["entity_type"] == "select"
        assert entities["status"]["entity_type"] == "sensor"
        assert await client.write_point(points[2], "ZX") == "ZX"
        assert await client.write_point(points[3], "cool") == "cool"
    finally:
        await client.close()
        await device.close()


@pytest.mark.anyio
async def test_parent_tcp_profile_creates_entities_and_routes_named_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = ModbusTCPDevice()
    await device.start()
    config = DeviceConfig(
        id="tcp-profile",
        host=f"127.0.0.1:{device.port}",
        transport="tcp",
        profile_id="test.tcp-profile",
        points=profile_points(),
    )
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    try:
        await state.apply_config(config)
        entities = {entity["id"]: entity for entity in state.all_entities()}
        assert entities["tcp-profile:voltage"]["state"]["point_value"] == pytest.approx(230.5)
        assert entities["tcp-profile:relay"]["entity_type"] == "switch"
        assert entities["tcp-profile:setpoint"]["entity_type"] == "number"
        result = await state.execute_tcp_command(
            config_id="tcp-profile",
            device_id="tcp-profile:setpoint",
            command="set_value",
            args={"value": 55, "address": 999, "unit_id": 247},
        )
        assert result == {"ok": True, "point_id": "setpoint", "value": 55.0}
        assert device.registers[10] == 55
    finally:
        await state.remove_config("tcp-profile")
        await device.close()
