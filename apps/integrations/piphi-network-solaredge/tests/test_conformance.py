from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from solar_edge import service as service_module
from solar_edge.main import app
from solar_edge.solaredge_client import SolarEdgeReading
from solar_edge.state import registry, solaredge_service

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "contract-conformance.json").read_text())


@pytest.mark.anyio
async def test_runtime_conforms_to_shared_contract_fixtures(monkeypatch) -> None:
    monkeypatch.setattr(service_module, "schedule_telemetry_delivery", lambda **_kwargs: None)
    solaredge_service.client_factory = FakeSolarEdgeClient
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for fixture in FIXTURES["cases"]:
                response = await client.request(fixture["method"], fixture["path"], json=fixture.get("body"))
                assert response.status_code == fixture["status"], fixture["id"]
                body = response.json()
                _assert_required_keys(body, fixture.get("required_keys", []), fixture["id"])
                _assert_required_any_keys(body, fixture.get("required_any_keys", []), fixture["id"])
                if fixture["id"] == "entities":
                    assert body["entities"][0]["entity_type"] == "solar_energy_system"
                    assert "production_power_w" in body["capabilities"]
            state_response = await client.get("/state")
            assert "test-api-key" not in state_response.text
    finally:
        await solaredge_service.close()
        for config_id in list(registry.ids()):
            registry.remove(config_id)


class FakeSolarEdgeClient:
    async def authenticate(self, _config) -> None:
        return None

    async def read(self, *, include_summary: bool) -> SolarEdgeReading:
        return SolarEdgeReading(
            site_id=1234567, site_name="Home solar", site_status="Active",
            last_update="2026-09-01 12:00:00", unit="kW",
            production_power_w=4200.0, consumption_power_w=1800.0,
            grid_power_w=-2400.0, battery_power_w=None, battery_soc_percent=None,
            today_energy_kwh=18.2, month_energy_kwh=410.0,
            year_energy_kwh=5100.0, lifetime_energy_kwh=24500.0,
        )

    async def close(self) -> None:
        return None


def _assert_required_keys(body: dict[str, Any], keys: list[str], fixture_id: str) -> None:
    for key in keys:
        assert key in body, f"{fixture_id} missing {key}"


def _assert_required_any_keys(body: dict[str, Any], groups: list[list[str]], fixture_id: str) -> None:
    for group in groups:
        assert any(key in body for key in group), f"{fixture_id} missing one of {', '.join(group)}"
