from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from xknx.dpt.dpt_1 import DPTSwitch
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueResponse

import piphi_network_knx.protocol as protocol
from piphi_network_knx.protocol import XknxClient, decode_value, encode_value
from piphi_network_knx.schemas import DeviceConfig, DptType


class FakeXknx:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.telegrams: asyncio.Queue = asyncio.Queue()
        self.connection_manager = SimpleNamespace(connected=asyncio.Event())
        self.stopped = False

    async def start(self) -> None:
        self.connection_manager.connected.set()

    async def stop(self) -> None:
        self.connection_manager.connected.clear()
        self.stopped = True


@pytest.mark.parametrize(
    ("dpt", "value", "expected"),
    [
        (DptType.SWITCH, True, True),
        (DptType.SCALING, 42, 42),
        (DptType.TEMPERATURE, 21.5, 21.5),
    ],
)
def test_dpt_round_trip(dpt, value, expected) -> None:
    assert decode_value(dpt, encode_value(dpt, value)) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("dpt", "value"),
    [
        (DptType.SWITCH, 1),
        (DptType.SCALING, -1),
        (DptType.SCALING, 101),
        (DptType.TEMPERATURE, "warm"),
    ],
)
def test_dpt_boundaries_fail_closed(dpt, value) -> None:
    with pytest.raises(ValueError):
        encode_value(dpt, value)


@pytest.mark.anyio
async def test_xknx_adapter_lifecycle_read_write_and_feedback(monkeypatch) -> None:
    monkeypatch.setattr(protocol, "XKNX", FakeXknx)
    values = []
    connections = []
    config = DeviceConfig.model_validate(
        {
            "id": "test",
            "host": "192.0.2.1",
            "allow_writes": True,
            "datapoints": [
                {
                    "id": "light",
                    "name": "Light",
                    "entity_type": "light",
                    "dpt": "1.001",
                    "state_address": "1/1/1",
                    "command_address": "1/1/2",
                    "writable": True,
                }
            ],
        }
    )
    client = XknxClient(config, lambda key, value: values.append((key, value)), connections.append)
    await client.start()
    assert client.connected
    await client.read(config.datapoints[0])
    await client.write(config.datapoints[0], True)
    sent = [await client._xknx.telegrams.get(), await client._xknx.telegrams.get()]
    assert [str(item.destination_address) for item in sent] == ["1/1/1", "1/1/2"]

    client._telegram_received(
        Telegram(
            GroupAddress("1/1/1"),
            payload=GroupValueResponse(DPTSwitch.to_knx(True)),
        )
    )
    assert values == [("light", True)]
    client._connection_changed(protocol.XknxConnectionState.DISCONNECTED)
    assert connections == [False]
    await client.stop()


@pytest.mark.anyio
async def test_discovery_normalizes_gateway(monkeypatch) -> None:
    class Scanner:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def async_scan(self):
            yield SimpleNamespace(
                serial_number="123",
                ip_addr="192.0.2.20",
                port=3671,
                name="Gateway",
                supports_tunnelling=True,
                supports_tunnelling_tcp=False,
            )

    monkeypatch.setattr(protocol, "GatewayScanner", Scanner)
    gateways = await protocol.discover_gateways()
    assert gateways == [
        {
            "id": "knx-ip-123",
            "device_id": "knx-ip-123",
            "host": "192.0.2.20",
            "port": 3671,
            "alias": "Gateway",
            "serial_number": "123",
            "supports_tunneling": True,
            "supports_tcp": False,
        }
    ]
