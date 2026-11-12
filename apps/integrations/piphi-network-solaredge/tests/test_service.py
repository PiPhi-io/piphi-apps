from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from solar_edge import service as service_module
from solar_edge.schemas import DeviceConfig
from solar_edge.service import SolarEdgeRuntimeService
from solar_edge.solaredge_client import SolarEdgeReading


class FakeRegistry:
    def __init__(self):
        self.states = {}
        self.state_snapshots = {}

    def update_state(self, config_id, state, *, device_id):
        self.states[config_id] = {**state, "device_id": device_id}
        self.state_snapshots[config_id] = {"state": dict(state)}


class FakeClient:
    def __init__(self):
        self.auth_calls = 0
        self.read_calls = []
        self.closed = False

    async def authenticate(self, _config):
        self.auth_calls += 1

    async def read(self, *, include_summary):
        self.read_calls.append(include_summary)
        return SolarEdgeReading(1234567, "Home solar", "Active", None, "W", 3200.0, 1400.0, -1800.0, None, None, today_energy_kwh=12.4)

    async def close(self):
        self.closed = True


class FailingClient(FakeClient):
    async def read(self, *, include_summary):
        self.read_calls.append(include_summary)
        raise RuntimeError("SolarEdge temporarily unavailable")


def config(config_id="site-one", site_id=1234567):
    return DeviceConfig(id=config_id, site_id=site_id, api_key="secret", poll_interval_seconds=3600)


@pytest.mark.anyio
async def test_service_reuses_client_delivers_telemetry_and_enforces_instance_limit(monkeypatch):
    deliveries = []
    monkeypatch.setattr(service_module, "schedule_telemetry_delivery", lambda **kwargs: deliveries.append(kwargs))
    clients = []

    def factory():
        result = FakeClient()
        clients.append(result)
        return result

    registry = FakeRegistry()
    service = SolarEdgeRuntimeService(
        registry=registry, runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(), client_factory=factory,
    )
    entry = {"config_id": "site-one", "device_id": "solaredge-1234567", "container_id": "container-1"}
    await service.configure(config(), entry)
    await service.configure(config(), entry)

    assert len(clients) == 1
    assert clients[0].auth_calls == 1
    assert clients[0].read_calls == [True]
    assert registry.states["site-one"]["grid_power_w"] == -1800.0
    assert deliveries[0]["metrics"] == {
        "connected": True,
        "read_failed": False,
        "production_power_w": 3200.0,
        "consumption_power_w": 1400.0,
        "grid_power_w": -1800.0,
    }
    assert deliveries[1]["metrics"] == {"today_energy_kwh": 12.4}
    assert deliveries[0]["timestamp"]
    assert service.poll_status["site-one"]["last_sample_recorded_at"]

    with pytest.raises(HTTPException) as exc_info:
        await service.configure(config("site-two", 7654321), {"config_id": "site-two", "device_id": "solaredge-7654321"})
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "instance_limit_reached"

    await service.close()
    assert clients[0].closed is True


@pytest.mark.anyio
async def test_summary_history_is_deduplicated_but_live_heartbeat_continues(monkeypatch):
    deliveries = []
    monkeypatch.setattr(service_module, "schedule_telemetry_delivery", lambda **kwargs: deliveries.append(kwargs))
    client = FakeClient()
    service = SolarEdgeRuntimeService(
        registry=FakeRegistry(), runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(), client_factory=lambda: client,
    )
    entry = {"config_id": "site-one", "device_id": "solaredge-1234567", "container_id": "container-1"}
    await service.configure(config(), entry)
    await service.refresh(force_summary=True)

    assert len(deliveries) == 3
    assert deliveries[0]["metrics"]["connected"] is True
    assert deliveries[1]["metrics"] == {"today_energy_kwh": 12.4}
    assert deliveries[2]["metrics"]["production_power_w"] == 3200.0
    assert "today_energy_kwh" not in deliveries[2]["metrics"]
    await service.close()


@pytest.mark.anyio
async def test_failed_read_preserves_last_values_and_sends_failure_heartbeat(monkeypatch):
    deliveries = []
    monkeypatch.setattr(service_module, "schedule_telemetry_delivery", lambda **kwargs: deliveries.append(kwargs))
    registry = FakeRegistry()
    registry.state_snapshots["site-one"] = {"state": {"production_power_w": 1700.0}}
    service = SolarEdgeRuntimeService(
        registry=registry, runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(), client_factory=FailingClient,
    )
    active = service_module.ActiveSession(
        config=config(), client=FailingClient(),
        entry={"config_id": "site-one", "device_id": "solaredge-1234567", "container_id": "container-1"},
        credentials_key=(1234567, "secret"),
    )
    service._active = active

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await service.refresh()

    assert registry.states["site-one"]["production_power_w"] == 1700.0
    assert registry.states["site-one"]["connected"] is False
    assert registry.states["site-one"]["read_failed"] is True
    assert deliveries[-1]["metrics"] == {"connected": False, "read_failed": True}
    assert service.freshness_summary()["read_failure_count"] == 1
    await service.close()
