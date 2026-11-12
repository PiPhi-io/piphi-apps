from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from piphi_network_sense import service as service_module
from piphi_network_sense.extended_api import SenseTimelineEvent
from piphi_network_sense.schemas import DeviceConfig
from piphi_network_sense.sense_client import SenseDeviceReading, SenseReading
from piphi_network_sense.service import SenseRuntimeService


class FakeRegistry:
    def __init__(self) -> None:
        self.states = {}

    def update_state(self, config_id, state, *, device_id):
        self.states[config_id] = {**state, "device_id": device_id}


class FakeClient:
    def __init__(self) -> None:
        self.monitor_id = "monitor-1"
        self.auth_calls = 0
        self.read_calls = []
        self.closed = False

    async def authenticate(self, _config) -> None:
        self.auth_calls += 1

    async def read(self, *, include_trends: bool) -> SenseReading:
        self.read_calls.append(include_trends)
        return SenseReading(
            monitor_id=self.monitor_id,
            time_zone="America/New_York",
            active_power_w=1000.0,
            active_solar_power_w=400.0,
            voltage_v=(121.0, 122.0),
            frequency_hz=60.0,
            daily_usage_kwh=7.5,
            daily_production_kwh=2.5,
            devices=(
                SenseDeviceReading(
                    "oven", "Oven", "oven", 800.0, True, 1.2,
                    device_type="Oven", first_usage="2025-01-12", timeline_enabled=True,
                ),
            ),
            always_on_power_w=125.0,
            other_power_w=75.0,
            timeline_events=(
                SenseTimelineEvent(
                    "event-1", "2026-08-31T21:57:43Z", "DeviceOn", "Oven turned on",
                    device_id="oven", device_name="Oven", icon="oven",
                ),
            ),
        )

    async def close(self) -> None:
        self.closed = True


def config(config_id: str, email: str = "owner@example.com") -> DeviceConfig:
    return DeviceConfig(id=config_id, email=email, password="secret", poll_interval_seconds=3600)


@pytest.mark.anyio
async def test_service_reuses_one_client_and_rejects_second_instance(monkeypatch) -> None:
    deliveries = []
    monkeypatch.setattr(
        service_module,
        "schedule_telemetry_delivery",
        lambda **kwargs: deliveries.append(kwargs),
    )
    clients = []

    def factory():
        client = FakeClient()
        clients.append(client)
        return client

    registry = FakeRegistry()
    service = SenseRuntimeService(
        registry=registry,
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
        client_factory=factory,
    )
    entry = {"config_id": "config-1", "device_id": "monitor-1", "container_id": "container-1"}
    await service.configure(config("config-1"), entry)
    await service.configure(config("config-1"), entry)

    assert len(clients) == 1
    assert clients[0].auth_calls == 1
    assert clients[0].read_calls == [True]
    assert registry.states["config-1"]["active_power_w"] == 1000.0
    assert registry.states["config-1"]["voltage_l2_v"] == 122.0
    assert registry.states["config-1"]["always_on_power_w"] == 125.0
    assert registry.states["config-1"]["other_power_w"] == 75.0
    assert registry.states["config-1"]["devices"][0]["device_type"] == "Oven"
    assert registry.states["config-1"]["timeline_events"][0]["event_id"] == "event-1"
    assert [delivery["device_id"] for delivery in deliveries] == ["monitor-1", "oven"]
    assert deliveries[1]["metrics"] == {
        "device_power_w": 800.0,
        "device_on": True,
        "device_daily_energy_kwh": 1.2,
    }
    assert deliveries[1]["units"]["device_on"] == "bool"

    with pytest.raises(HTTPException) as exc_info:
        await service.configure(
            config("config-2", "other@example.com"),
            {"config_id": "config-2", "device_id": "monitor-2"},
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "instance_limit_reached"

    await service.close()
    assert clients[0].closed is True
