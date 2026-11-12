from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from piphi_network_sense import service as service_module
from piphi_network_sense.main import app
from piphi_network_sense.sense_client import SenseDeviceReading, SenseReading
from piphi_network_sense.state import registry, sense_service


FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text())


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures(monkeypatch) -> None:
    monkeypatch.setattr(service_module, "schedule_telemetry_delivery", lambda **_kwargs: None)
    sense_service.client_factory = FakeSenseClient
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for fixture in FIXTURES["cases"]:
                response = await client.request(
                    fixture["method"],
                    fixture["path"],
                    json=fixture.get("body"),
                )
                assert response.status_code == fixture["status"], fixture["id"]
                body = response.json()
                _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
                _assert_required_any_keys(body, fixture.get("required_any_keys", []), fixture["id"])
                if fixture["id"] == "entities":
                    appliance = next(
                        entity for entity in body["entities"] if entity["device_id"] == "device-1"
                    )
                    assert appliance["metadata"]["sense_device_type"] == "Refrigerator"
                    assert "always_on_power_w" in body["capabilities"]
    finally:
        await sense_service.close()
        for config_id in list(registry.ids()):
            registry.remove(config_id)


class FakeSenseClient:
    monitor_id = "monitor-123"

    async def authenticate(self, _config) -> None:
        return None

    async def read(self, *, include_trends: bool) -> SenseReading:
        return SenseReading(
            monitor_id=self.monitor_id,
            time_zone="America/New_York",
            active_power_w=842.5,
            active_solar_power_w=250.0,
            voltage_v=(121.1, 120.8),
            frequency_hz=60.0,
            daily_usage_kwh=8.4,
            daily_production_kwh=3.2,
            daily_from_grid_kwh=5.5,
            daily_to_grid_kwh=0.3,
            devices=(
                SenseDeviceReading(
                    "device-1", "Refrigerator", "fridge", 112.0, True, 1.4,
                    device_type="Refrigerator", first_usage="2025-01-12",
                    timeline_enabled=True,
                ),
            ),
        )

    async def close(self) -> None:
        return None


def _assert_required_keys(body: dict[str, Any], keys: list[str], fixture_id: str) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(body: dict[str, Any], groups: list[list[str]], fixture_id: str) -> None:
    for group in groups:
        assert any(key in body for key in group), f"{fixture_id} missing one of {', '.join(group)}"
