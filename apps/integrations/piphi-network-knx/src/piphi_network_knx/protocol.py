from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from xknx import XKNX
from xknx.core.connection_state import XknxConnectionState
from xknx.dpt.dpt_1 import DPTSwitch
from xknx.dpt.dpt_5 import DPTScaling
from xknx.dpt.dpt_9 import DPTTemperature
from xknx.dpt.payload import DPTArray, DPTBinary
from xknx.io import ConnectionConfig, ConnectionType, GatewayScanner
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

from .schemas import DatapointConfig, DeviceConfig, DptType, TransportMode

ValueCallback = Callable[[str, Any], None]
ConnectionCallback = Callable[[bool], None]


class KnxClient(Protocol):
    @property
    def connected(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def read(self, datapoint: DatapointConfig) -> None: ...

    async def write(self, datapoint: DatapointConfig, value: Any) -> None: ...


@dataclass(slots=True)
class _Operation:
    telegram: Telegram
    completed: asyncio.Future[None]


_DPT_CLASSES = {
    DptType.SWITCH: DPTSwitch,
    DptType.SCALING: DPTScaling,
    DptType.TEMPERATURE: DPTTemperature,
}


def encode_value(dpt: DptType, value: Any) -> DPTArray | DPTBinary:
    if dpt == DptType.SWITCH and type(value) is not bool:
        raise ValueError("DPT 1.001 requires a boolean")
    if dpt in {DptType.SCALING, DptType.TEMPERATURE} and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise ValueError(f"DPT {dpt} requires a number")
    if dpt == DptType.SCALING and not 0 <= float(value) <= 100:
        raise ValueError("DPT 5.001 must be between 0 and 100")
    if dpt == DptType.TEMPERATURE and not -273 <= float(value) <= 670760:
        raise ValueError("DPT 9.001 temperature is outside the supported range")
    return _DPT_CLASSES[dpt].to_knx(value)


def decode_value(dpt: DptType, payload: DPTArray | DPTBinary) -> Any:
    value = _DPT_CLASSES[dpt].from_knx(payload)
    if dpt == DptType.SWITCH:
        return bool(value.value)
    return value


class XknxClient:
    """Bounded xknx adapter for one exclusive KNX/IP tunnel."""

    def __init__(
        self,
        config: DeviceConfig,
        on_value: ValueCallback,
        on_connection: ConnectionCallback,
    ) -> None:
        self._config = config
        self._on_value = on_value
        self._on_connection = on_connection
        self._datapoints = {item.state_address: item for item in config.datapoints}
        connection_type = {
            TransportMode.AUTOMATIC: ConnectionType.AUTOMATIC,
            TransportMode.TUNNELING_UDP: ConnectionType.TUNNELING,
            TransportMode.TUNNELING_TCP: ConnectionType.TUNNELING_TCP,
        }[config.transport]
        self._xknx = XKNX(
            connection_config=ConnectionConfig(
                connection_type=connection_type,
                gateway_ip=config.host,
                gateway_port=config.port,
                local_ip=config.local_ip,
                auto_reconnect=True,
            ),
            rate_limit=config.rate_limit,
            telegram_received_cb=self._telegram_received,
            connection_state_changed_cb=self._connection_changed,
        )
        self._queue: asyncio.Queue[_Operation] = asyncio.Queue(maxsize=config.queue_size)
        self._worker: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._xknx.connection_manager.connected.is_set()

    async def start(self) -> None:
        await asyncio.wait_for(self._xknx.start(), self._config.connect_timeout_seconds)
        if not self.connected:
            await self._xknx.stop()
            raise ConnectionError("KNX/IP session did not become connected")
        self._worker = asyncio.create_task(self._send_worker(), name="knx-send-worker")

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None
        while not self._queue.empty():
            operation = self._queue.get_nowait()
            if not operation.completed.done():
                operation.completed.set_exception(ConnectionError("KNX session stopped"))
            self._queue.task_done()
        await self._xknx.stop()

    async def read(self, datapoint: DatapointConfig) -> None:
        await self._enqueue(
            Telegram(GroupAddress(datapoint.state_address), payload=GroupValueRead())
        )

    async def write(self, datapoint: DatapointConfig, value: Any) -> None:
        if datapoint.command_address is None:
            raise ValueError("datapoint is not writable")
        payload = GroupValueWrite(encode_value(datapoint.dpt, value))
        await self._enqueue(Telegram(GroupAddress(datapoint.command_address), payload=payload))

    async def _enqueue(self, telegram: Telegram) -> None:
        if not self.connected:
            raise ConnectionError("KNX/IP session is disconnected")
        loop = asyncio.get_running_loop()
        completed: asyncio.Future[None] = loop.create_future()
        try:
            self._queue.put_nowait(_Operation(telegram, completed))
        except asyncio.QueueFull as exc:
            raise RuntimeError("KNX outgoing queue is full") from exc
        await asyncio.wait_for(completed, self._config.command_timeout_seconds)

    async def _send_worker(self) -> None:
        while True:
            operation = await self._queue.get()
            try:
                await self._xknx.telegrams.put(operation.telegram)
                if not operation.completed.done():
                    operation.completed.set_result(None)
            except Exception as exc:  # xknx exposes transport-specific errors
                if not operation.completed.done():
                    operation.completed.set_exception(exc)
            finally:
                self._queue.task_done()

    def _connection_changed(self, state: Any) -> None:
        self._on_connection(state == XknxConnectionState.CONNECTED)

    def _telegram_received(self, telegram: Telegram) -> None:
        datapoint = self._datapoints.get(str(telegram.destination_address))
        payload = telegram.payload
        if datapoint is None or not isinstance(payload, (GroupValueWrite, GroupValueResponse)):
            return
        try:
            value = decode_value(datapoint.dpt, payload.value)
        except (ValueError, TypeError):
            return
        self._on_value(datapoint.id, value)


async def discover_gateways(local_ip: str | None = None) -> list[dict[str, Any]]:
    xknx = XKNX()
    scanner = GatewayScanner(xknx, local_ip=local_ip, timeout_in_seconds=3.0)
    gateways: list[dict[str, Any]] = []
    async for gateway in scanner.async_scan():
        gateways.append(
            {
                "id": f"knx-ip-{gateway.serial_number}",
                "device_id": f"knx-ip-{gateway.serial_number}",
                "host": str(gateway.ip_addr),
                "port": gateway.port,
                "alias": gateway.name or "KNX/IP interface",
                "serial_number": str(gateway.serial_number),
                "supports_tunneling": bool(gateway.supports_tunnelling),
                "supports_tcp": bool(gateway.supports_tunnelling_tcp),
            }
        )
    return gateways
