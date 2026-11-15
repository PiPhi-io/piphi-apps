from __future__ import annotations

import asyncio
import random
import ssl
import struct

import pytest

from piphi_network_modbus import modbus_tcp
from piphi_network_modbus.modbus_tcp import (
    MBAP,
    ModbusTCPClient,
    ReadBlock,
    frame_with_crc,
    validate_rtu_frame,
)
from piphi_network_modbus.schemas import DeviceConfig
from piphi_network_modbus.schemas import PointProfile


def read_response(function: int, value: int = 0x1234) -> bytes:
    return bytes([function, 2]) + value.to_bytes(2, "big")


class UDPDevice(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.requests: list[bytes] = []

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, address) -> None:
        self.requests.append(data)
        transaction, protocol, _length, unit = MBAP.unpack(data[: MBAP.size])
        function = data[MBAP.size]
        response = read_response(function)
        self.transport.sendto(
            MBAP.pack(transaction, protocol, len(response) + 1, unit) + response,
            address,
        )


@pytest.mark.anyio
async def test_udp_uses_mbap_and_reads_profile_data() -> None:
    loop = asyncio.get_running_loop()
    protocol = UDPDevice()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol, local_addr=("127.0.0.1", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    client = ModbusTCPClient(f"127.0.0.1:{port}", transport="udp")
    try:
        values = await client.read_block(ReadBlock(7, "holding_register", 42, 1, ()))
        assert values == [0x1234]
        assert MBAP.unpack(protocol.requests[0][: MBAP.size])[3] == 7
    finally:
        await client.close()
        transport.close()


@pytest.mark.anyio
async def test_rtu_over_tcp_uses_crc_framing() -> None:
    requests: list[bytes] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        request = await reader.readexactly(8)
        requests.append(request)
        assert validate_rtu_frame(request, unit_id=7, function=3) == struct.pack(
            ">HH", 42, 1
        )
        writer.write(frame_with_crc(bytes.fromhex("0703021234")))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = ModbusTCPClient(f"127.0.0.1:{port}", transport="rtu_over_tcp")
    try:
        assert await client.read_block(
            ReadBlock(7, "holding_register", 42, 1, ())
        ) == [0x1234]
        assert requests
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
async def test_tls_requires_ca_and_enables_hostname_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="tls_ca_certificate_required"):
        ModbusTCPClient("meter.local", transport="tls")

    context = type("Context", (), {})()
    seen: dict[str, object] = {}

    def context_factory(*, cafile: str):
        seen["cafile"] = cafile
        return context

    class Writer:
        def is_closing(self) -> bool:
            return False

    async def open_connection(host, port, **kwargs):
        seen.update(host=host, port=port, **kwargs)
        return asyncio.StreamReader(), Writer()

    monkeypatch.setattr(modbus_tcp.ssl, "create_default_context", context_factory)
    monkeypatch.setattr(modbus_tcp.asyncio, "open_connection", open_connection)
    client = ModbusTCPClient(
        "meter.local",
        transport="tls",
        tls_ca_certificate="/run/secrets/modbus-ca.pem",
        tls_server_name="meter.local",
    )
    await client._connect_locked()
    assert seen["cafile"] == "/run/secrets/modbus-ca.pem"
    assert seen["ssl"] is context
    assert seen["server_hostname"] == "meter.local"
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_transport_configuration_fails_closed() -> None:
    point = {
        "id": "value",
        "name": "Value",
        "unit_id": 1,
        "address": 0,
        "area": "holding_register",
        "data_type": "uint16",
    }
    with pytest.raises(ValueError, match="tls transport requires"):
        DeviceConfig.model_validate(
            {"id": "tls", "host": "meter.local", "transport": "tls", "points": [point]}
        )
    with pytest.raises(ValueError, match="TLS settings require"):
        DeviceConfig.model_validate(
            {
                "id": "clear",
                "host": "meter.local",
                "transport": "tcp",
                "tls_ca_certificate": "/run/secrets/ca.pem",
                "points": [point],
            }
        )
    for transport in ("tcp", "udp", "rtu_over_tcp"):
        assert (
            DeviceConfig.model_validate(
                {
                    "id": transport.replace("_", "-"),
                    "host": "meter.local",
                    "transport": transport,
                    "points": [point],
                }
            ).transport
            == transport
        )
    assert (
        DeviceConfig.model_validate(
            {
                "id": "secure",
                "host": "meter.local",
                "transport": "tls",
                "tls_ca_certificate": "/run/secrets/ca.pem",
                "points": [point],
            }
        ).transport
        == "tls"
    )


def test_block_planner_randomized_never_reads_profile_holes() -> None:
    generator = random.Random(20261115)
    for _ in range(200):
        points: list[PointProfile] = []
        address = 0
        for index in range(generator.randint(1, 40)):
            address += generator.randint(0, 3)
            points.append(
                PointProfile(
                    id=f"point_{index}",
                    name=f"Point {index}",
                    unit_id=generator.randint(1, 3),
                    area="holding_register",
                    address=address,
                    data_type="uint16",
                )
            )
            address += 1
        for block in modbus_tcp.plan_read_blocks(points):
            declared = {
                point.address
                for point in points
                if point.unit_id == block.unit_id and point.area == block.area
            }
            covered = set(range(block.address, block.address + block.quantity))
            assert covered <= declared
            assert block.quantity <= modbus_tcp.MAX_QUANTITY_BY_AREA[block.area]
