from __future__ import annotations

import pytest

from solar_edge.solaredge_client import MonitoringApiClient, _power_factor


class FakeUpstreamClient:
    async def get_current_power_flow(self, site_id):
        assert site_id == 1234567
        return {"siteCurrentPowerFlow": {
            "unit": "kW",
            "connections": [{"from": "PV", "to": "Load"}, {"from": "PV", "to": "GRID"}, {"from": "STORAGE", "to": "Load"}],
            "PV": {"status": "Active", "currentPower": 5.2},
            "LOAD": {"status": "Active", "currentPower": 2.1},
            "GRID": {"status": "Active", "currentPower": 3.1},
            "STORAGE": {"status": "Discharging", "currentPower": 0.4, "chargeLevel": 72},
        }}

    async def get_overview(self, site_ids):
        assert site_ids == [1234567]
        return {"overview": {
            "lastUpdateTime": "2026-09-01 12:00:00",
            "lastDayData": {"energy": 18500.0}, "lastMonthData": {"energy": 402000.0},
            "lastYearData": {"energy": 5100000.0},
            "lifeTimeData": {"energy": 24500000.0, "revenue": 3210.5},
        }}


@pytest.mark.anyio
async def test_adapter_normalizes_units_directions_and_energy() -> None:
    client = MonitoringApiClient()
    client._client = FakeUpstreamClient()
    client._site_id = 1234567
    client._site_name = "Home solar"
    client._site_status = "Active"

    reading = await client.read(include_summary=True)

    assert reading.production_power_w == 5200.0
    assert reading.consumption_power_w == 2100.0
    assert reading.grid_power_w == -3100.0
    assert reading.battery_power_w == 400.0
    assert reading.battery_soc_percent == 72.0
    assert reading.today_energy_kwh == 18.5
    assert reading.lifetime_energy_kwh == 24500.0
    assert reading.lifetime_revenue == 3210.5


def test_unknown_power_unit_safely_falls_back_to_watts() -> None:
    assert _power_factor("kW") == 1000.0
    assert _power_factor("unexpected") == 1.0
