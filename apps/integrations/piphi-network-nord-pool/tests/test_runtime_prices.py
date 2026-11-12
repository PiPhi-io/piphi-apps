from __future__ import annotations

from typing import Any

import httpx
import pytest

from piphi_network_nord_pool import state
from piphi_network_nord_pool.main import app
from piphi_network_nord_pool.market_client import MarketDataError


@pytest.mark.anyio
async def test_refresh_exposes_real_prices_and_retains_last_good_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_telemetry: list[dict[str, Any]] = []

    async def prices(**_: Any) -> dict[str, Any]:
        return {
            "market_area": "SE3",
            "price_unit": "EUR/kWh",
            "current_price_per_kwh": 0.123,
            "next_price_per_kwh": 0.145,
        }

    monkeypatch.setattr(state, "fetch_prices", prices)
    monkeypatch.setattr(
        state,
        "schedule_telemetry_delivery",
        lambda **kwargs: observed_telemetry.append(kwargs),
    )
    transport = httpx.ASGITransport(app=app)
    config_id = "runtime-prices-test"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        try:
            configured = await client.post(
                "/config",
                json={
                    "id": "setup-row-runtime-prices",
                    "config_id": config_id,
                    "market_area": "se3",
                    "currency": "EUR",
                    "api_key": "must-not-appear-in-state",
                },
            )
            assert configured.status_code == 200
            entities = (await client.get("/entities")).json()["entities"]
            assert any(
                entity["config_id"] == config_id
                and "current_price_per_kwh" in entity["capabilities"]
                for entity in entities
            )

            refreshed = await client.post(
                "/command",
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "target": {"config_id": config_id, "device_id": config_id},
                    "params": {},
                    "capability": "device.refresh",
                    "capability_requirements": ["device.refresh"],
                },
            )
            assert refreshed.status_code == 200
            assert refreshed.json()["state"]["current_price_per_kwh"] == 0.123
            assert observed_telemetry[-1]["metrics"]["current_price_per_kwh"] == 0.123
            snapshot = (await client.get("/state")).json()
            assert snapshot["state_snapshots"][config_id]["state"]["connected"] is True
            assert "must-not-appear-in-state" not in str(snapshot)

            async def unavailable(**_: Any) -> dict[str, Any]:
                raise MarketDataError("market data request failed")

            monkeypatch.setattr(state, "fetch_prices", unavailable)
            failed = await client.post(
                "/command",
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "target": {"config_id": config_id, "device_id": config_id},
                    "params": {},
                    "capability": "device.refresh",
                },
            )
            assert failed.status_code == 502
            latest = (await client.get("/state")).json()["state_snapshots"][config_id]["state"]
            assert latest["connected"] is False
            assert latest["current_price_per_kwh"] == 0.123
        finally:
            await client.post(f"/deconfigure/{config_id}")


@pytest.mark.anyio
async def test_configuration_rejects_missing_market_area() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/config", json={"id": "invalid", "host": "127.0.0.1"})
    assert response.status_code == 422
