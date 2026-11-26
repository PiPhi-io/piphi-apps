from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from piphi_modbus_rtu_sidecar.schemas import DeviceConfig
from piphi_modbus_rtu_sidecar.transport import BoundedQueue


class ScriptedSerialSession:
    """Configurable serial boundary shared by lifecycle and HTTP tests."""

    def __init__(self, config: DeviceConfig, events: list[tuple[str, str]]) -> None:
        self.config = config
        self.events = events
        self.queue = BoundedQueue(config.queue_capacity)
        self.open_calls = 0
        self.close_calls = 0
        self.opened = False
        self.open_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.read_outcomes: list[list[int | bool] | BaseException] = []
        self.values = {
            (point.unit_id, point.address): (
                [False] if point.area == "coil" else [42] * point.width
            )
            for point in config.registers
        }

    async def open(self) -> None:
        self.open_calls += 1
        self.events.append(("open", self.config.id))
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append(("close", self.config.id))
        self.opened = False
        if self.close_error is not None:
            raise self.close_error

    async def read(self, point) -> list[int | bool]:
        if self.read_outcomes:
            outcome = self.read_outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        return self.values[(point.unit_id, point.address)]

    async def write(self, point, values: list[int | bool]) -> None:
        self.values[(point.unit_id, point.address)] = values

    async def write_coils(self, points, values: list[bool]) -> None:
        for point, value in zip(points, values, strict=True):
            self.values[(point.unit_id, point.address)] = [value]


class ScriptedSessionFactory:
    def __init__(self) -> None:
        self.sessions: list[ScriptedSerialSession] = []
        self.events: list[tuple[str, str]] = []
        self.next_open_error: BaseException | None = None

    def __call__(self, config: DeviceConfig) -> ScriptedSerialSession:
        session = ScriptedSerialSession(config, self.events)
        session.open_error = self.next_open_error
        self.next_open_error = None
        self.sessions.append(session)
        return session


@pytest.fixture
def scripted_session_factory() -> ScriptedSessionFactory:
    return ScriptedSessionFactory()


@pytest.fixture
def sidecar_config() -> Callable[..., DeviceConfig]:
    def build(config_id: str = "test-bus", **updates: Any) -> DeviceConfig:
        values: dict[str, Any] = {
            "id": config_id,
            "serial_port": f"/dev/serial/by-id/{config_id}",
            "registers": [
                {
                    "id": "value",
                    "name": "Value",
                    "unit_id": 1,
                    "address": 0,
                }
            ],
        }
        values.update(updates)
        return DeviceConfig.model_validate(values)

    return build
