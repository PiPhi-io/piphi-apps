from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest
from xknx import XKNX
from xknx.io import ConnectionConfig, ConnectionType
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

from piphi_network_knx.protocol import XknxClient, decode_value, encode_value
from piphi_network_knx.schemas import DeviceConfig, TransportMode

pytestmark = pytest.mark.skipif(
    os.getenv("PIPHI_KNX_VIRTUAL_TEST") != "1",
    reason="requires the opt-in knxd virtual bus fixture",
)

DATAPOINTS = [
    {
        "id": "switch",
        "name": "Virtual switch",
        "entity_type": "switch",
        "dpt": "1.001",
        "state_address": "1/0/1",
        "command_address": "1/1/1",
        "writable": True,
    },
    {
        "id": "scale",
        "name": "Virtual scale",
        "entity_type": "light",
        "dpt": "5.001",
        "state_address": "1/0/2",
        "command_address": "1/1/2",
        "writable": True,
    },
    {
        "id": "temperature",
        "name": "Virtual temperature",
        "entity_type": "sensor",
        "dpt": "9.001",
        "state_address": "1/0/3",
    },
]


async def _next_matching(
    queue: asyncio.Queue[Telegram],
    address: str,
    payload_type: type[Any],
) -> Telegram:
    async with asyncio.timeout(5):
        while True:
            telegram = await queue.get()
            if str(telegram.destination_address) == address and isinstance(
                telegram.payload, payload_type
            ):
                return telegram


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("mode", "connection_type"),
    [
        (TransportMode.AUTOMATIC, ConnectionType.TUNNELING),
        (TransportMode.TUNNELING_UDP, ConnectionType.TUNNELING),
        (TransportMode.TUNNELING_TCP, ConnectionType.TUNNELING_TCP),
    ],
)
async def test_real_xknx_client_over_virtual_knxd_bus(
    mode: TransportMode,
    connection_type: ConnectionType,
) -> None:
    host = os.getenv("PIPHI_KNX_VIRTUAL_HOST", "127.0.0.1")
    port = int(os.getenv("PIPHI_KNX_VIRTUAL_PORT", "3671"))
    observed: asyncio.Queue[Telegram] = asyncio.Queue()
    feedback: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    observer = XKNX(
        connection_config=ConnectionConfig(
            connection_type=connection_type,
            gateway_ip=host,
            gateway_port=port,
            auto_reconnect=False,
        ),
        telegram_received_cb=observed.put_nowait,
    )
    config = DeviceConfig.model_validate(
        {
            "id": f"virtual-{mode}",
            "host": host,
            "port": port,
            "transport": mode,
            "allow_writes": True,
            "connect_timeout_seconds": 5,
            "command_timeout_seconds": 5,
            "rate_limit": 20,
            "datapoints": DATAPOINTS,
        }
    )
    client = XknxClient(
        config, lambda key, value: feedback.put_nowait((key, value)), lambda _: None
    )

    await observer.start()
    await client.start()
    try:
        assert observer.connection_manager.connected.is_set()
        assert client.connected

        for datapoint, value in zip(config.datapoints[:2], (True, 42.0), strict=True):
            await client.write(datapoint, value)
            command = await _next_matching(
                observed,
                datapoint.command_address or "",
                GroupValueWrite,
            )
            decoded = decode_value(datapoint.dpt, command.payload.value)
            if isinstance(value, float):
                assert float(decoded) == pytest.approx(value, abs=0.5)
            else:
                assert decoded is value

        for datapoint, value in zip(config.datapoints, (False, 73.0, 21.5), strict=True):
            await observer.telegram_queue.process_telegram_outgoing(
                Telegram(
                    GroupAddress(datapoint.state_address),
                    payload=GroupValueWrite(encode_value(datapoint.dpt, value)),
                )
            )
            datapoint_id, decoded = await asyncio.wait_for(feedback.get(), 5)
            assert datapoint_id == datapoint.id
            if isinstance(value, float):
                assert float(decoded) == pytest.approx(value, abs=0.5)
            else:
                assert decoded is value

        temperature = config.datapoints[2]
        await client.read(temperature)
        await _next_matching(observed, temperature.state_address, GroupValueRead)
        await observer.telegram_queue.process_telegram_outgoing(
            Telegram(
                GroupAddress(temperature.state_address),
                payload=GroupValueResponse(encode_value(temperature.dpt, 22.25)),
            )
        )
        datapoint_id, decoded = await asyncio.wait_for(feedback.get(), 5)
        assert datapoint_id == temperature.id
        assert float(decoded) == pytest.approx(22.25, abs=0.05)
    finally:
        await client.stop()
        await observer.stop()
