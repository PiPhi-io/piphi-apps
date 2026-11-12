from __future__ import annotations

import asyncio

import pytest
from piphi_runtime_kit_python import create_runtime_starter

pytest.importorskip("piphi_runtime_testkit_python")

from solar_edge.schemas import DeviceConfig
from solar_edge.service import SolarEdgeRuntimeService
from solar_edge.solaredge_client import SolarEdgeReading


class TestKitSolarEdgeClient:
    async def authenticate(self, _config) -> None:
        return None

    async def read(self, *, include_summary: bool) -> SolarEdgeReading:
        assert include_summary is True
        return SolarEdgeReading(
            site_id=1234567, site_name="Test home", site_status="Active",
            last_update="2026-09-10 12:00:00", unit="W",
            production_power_w=4400.0, consumption_power_w=1900.0,
            grid_power_w=-2500.0, battery_power_w=None, battery_soc_percent=None,
            today_energy_kwh=19.2, month_energy_kwh=430.0,
            year_energy_kwh=5200.0, lifetime_energy_kwh=25000.0,
        )

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_runtime_sdk_delivers_widget_metrics_to_testkit_core(mock_core) -> None:
    starter = create_runtime_starter(
        integration_id="piphi-network-solaredge", integration_name="SolarEdge",
        version="0.2.2", core_base_url=mock_core.base_url,
    )
    starter.runtime.auth.update(container_id="runtime-test", internal_token="test-token")
    service = SolarEdgeRuntimeService(
        registry=starter.registry, runtime=starter.runtime,
        telemetry=starter.telemetry_client, client_factory=TestKitSolarEdgeClient,
    )
    entry = {
        "config_id": "site-one", "device_id": "solaredge-1234567",
        "container_id": "runtime-test", "integration_id": "piphi-network-solaredge",
    }
    starter.registry.set("site-one", entry)
    config = DeviceConfig(
        id="site-one", config_id="site-one", device_id="solaredge-1234567",
        container_id="runtime-test", integration_id="piphi-network-solaredge",
        site_id=1234567, api_key="fake-test-key", poll_interval_seconds=3600,
    )

    await service.configure(config, entry)
    pending = list(starter.runtime.process_state.background_tasks)
    if pending:
        await asyncio.gather(*pending)

    assert len(mock_core.telemetry_requests) == 2
    live_request = next(
        request
        for request in mock_core.telemetry_requests
        if "production_power_w" in request.json_body["metrics"]
    )
    summary_request = next(
        request
        for request in mock_core.telemetry_requests
        if "today_energy_kwh" in request.json_body["metrics"]
    )
    live = live_request.json_body
    summary = summary_request.json_body
    assert live["metrics"]["production_power_w"] == 4400.0
    assert live["metrics"]["connected"] is True
    assert "battery_power_w" not in live["metrics"]
    assert summary["metrics"]["today_energy_kwh"] == 19.2
    assert live["timestamp"] and summary["timestamp"]
    headers = {key.lower(): value for key, value in live_request.headers.items()}
    assert headers["x-container-id"] == "runtime-test"
    assert headers["x-piphi-integration-token"] == "test-token"
    assert service.poll_status["site-one"]["last_core_heartbeat_at"]
    await service.close()
