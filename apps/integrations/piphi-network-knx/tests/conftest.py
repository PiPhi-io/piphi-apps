from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from piphi_network_knx.protocol import encode_value
from piphi_network_knx.schemas import DatapointConfig, DeviceConfig
from piphi_network_knx.state import manager, registry


class FakeKnxClient:
    instances: list[FakeKnxClient] = []
    fail_next_start = False
    start_gate: asyncio.Event | None = None
    start_entered: asyncio.Event | None = None

    def __init__(self, config: DeviceConfig, on_value, on_connection) -> None:
        self.config = config
        self.on_value = on_value
        self.on_connection = on_connection
        self.is_connected = False
        self.reads: list[str] = []
        self.writes: list[tuple[str, Any]] = []
        self.fail_write: Exception | None = None
        self.__class__.instances.append(self)

    @property
    def connected(self) -> bool:
        return self.is_connected

    async def start(self) -> None:
        if self.__class__.fail_next_start:
            self.__class__.fail_next_start = False
            raise ConnectionError("test connection failure")
        if self.__class__.start_gate is not None:
            if self.__class__.start_entered is not None:
                self.__class__.start_entered.set()
            await self.__class__.start_gate.wait()
        self.is_connected = True
        self.on_connection(True)

    async def stop(self) -> None:
        self.is_connected = False

    async def read(self, datapoint: DatapointConfig) -> None:
        self.reads.append(datapoint.id)

    async def write(self, datapoint: DatapointConfig, value: Any) -> None:
        encode_value(datapoint.dpt, value)
        if self.fail_write is not None:
            raise self.fail_write
        self.writes.append((datapoint.id, value))

    def receive(self, datapoint_id: str, value: Any) -> None:
        self.on_value(datapoint_id, value)

    def disconnect(self) -> None:
        self.is_connected = False
        self.on_connection(False)


@pytest.fixture(autouse=True)
def allow_test_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")


@pytest.fixture
def fake_knx(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Iterator[type[FakeKnxClient]]:
    FakeKnxClient.instances.clear()
    FakeKnxClient.fail_next_start = False
    FakeKnxClient.start_gate = None
    FakeKnxClient.start_entered = None
    monkeypatch.setattr(manager, "client_factory", FakeKnxClient)
    monkeypatch.setattr(manager, "persistence_path", tmp_path / "knx-configs.json")
    yield FakeKnxClient
    manager.sessions.clear()
    manager._pending_endpoints.clear()
    for config_id in list(registry.ids()):
        registry.remove(config_id)
