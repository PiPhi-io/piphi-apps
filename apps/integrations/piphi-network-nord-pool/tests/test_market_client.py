from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from piphi_network_nord_pool.market_client import MarketDataError, fetch_prices
from piphi_network_nord_pool.pricing import normalize_prices

NOW = datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)


def response_payload(day: str, start: str, end: str, price: float) -> dict:
    return {
        "deliveryDateCET": day,
        "currency": "EUR",
        "updatedAt": "2026-09-20T10:00:00Z",
        "multiAreaEntries": [
            {
                "deliveryStart": start,
                "deliveryEnd": end,
                "entryPerArea": {"SE3": price},
            }
        ],
    }


@pytest.mark.anyio
async def test_fetches_current_and_next_interval_without_exposing_raw_response() -> None:
    today = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", 150
    )
    today["multiAreaEntries"].append(
        {
            "deliveryStart": "2026-09-20T13:00:00Z",
            "deliveryEnd": "2026-09-20T13:15:00Z",
            "entryPerArea": {"SE3": 160},
        }
    )
    tomorrow = response_payload(
        "2026-09-21", "2026-09-21T00:00:00Z", "2026-09-21T00:15:00Z", -20
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "dataportal-api.nordpoolgroup.com"
        assert request.url.params["deliveryArea"] == "SE3"
        assert request.url.params["currency"] == "EUR"
        day = request.url.params["date"]
        return httpx.Response(200, json=today if day == "2026-09-20" else tomorrow)

    result = await fetch_prices(
        area="SE3", currency="EUR", now=NOW, transport=httpx.MockTransport(handler)
    )
    assert result["current_price_per_kwh"] == 0.15
    assert result["next_price_per_kwh"] == 0.16
    assert result["price_unit"] == "EUR/kWh"
    assert result["market_area"] == "SE3"
    assert result["data_updated_at"] == "2026-09-20T10:00:00Z"
    assert len(result["chart_intervals"]) == 3
    assert "multiAreaEntries" not in result


@pytest.mark.anyio
async def test_unpublished_tomorrow_keeps_current_day() -> None:
    today = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", 100
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["date"] == "2026-09-21":
            return httpx.Response(204)
        return httpx.Response(200, json=today)

    result = await fetch_prices(
        area="SE3", currency="EUR", now=NOW, transport=httpx.MockTransport(handler)
    )
    assert result["current_price_per_kwh"] == 0.1
    assert result["next_price_per_kwh"] is None


@pytest.mark.anyio
async def test_does_not_merge_tomorrow_with_mismatched_currency() -> None:
    today = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", 100
    )
    tomorrow = response_payload(
        "2026-09-21", "2026-09-20T13:00:00Z", "2026-09-20T13:15:00Z", 200
    )
    tomorrow["currency"] = "SEK"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = today if request.url.params["date"] == "2026-09-20" else tomorrow
        return httpx.Response(200, json=payload)

    result = await fetch_prices(
        area="SE3", currency="EUR", now=NOW, transport=httpx.MockTransport(handler)
    )
    assert result["current_price_per_kwh"] == 0.1
    assert result["next_price_per_kwh"] is None
    assert len(result["chart_intervals"]) == 1


@pytest.mark.anyio
async def test_rejects_missing_current_market_data() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    with pytest.raises(MarketDataError, match="current market day"):
        await fetch_prices(
            area="SE3", currency="EUR", now=NOW, transport=httpx.MockTransport(handler)
        )


def test_rejects_nonfinite_and_overlapping_intervals() -> None:
    payload = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", float("nan")
    )
    with pytest.raises(ValueError, match="invalid price interval"):
        normalize_prices(payload, "SE3", NOW)

    payload["multiAreaEntries"][0]["entryPerArea"]["SE3"] = 100
    payload["multiAreaEntries"].append(
        {
            "deliveryStart": "2026-09-20T12:30:00Z",
            "deliveryEnd": "2026-09-20T13:30:00Z",
            "entryPerArea": {"SE3": 200},
        }
    )
    with pytest.raises(ValueError, match="overlapping"):
        normalize_prices(payload, "SE3", NOW)


def test_filters_other_market_areas() -> None:
    payload = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", 100
    )
    with pytest.raises(ValueError, match="selected market area"):
        normalize_prices(payload, "NO1", NOW)


def test_gap_does_not_mislabel_later_price_as_next_interval() -> None:
    payload = response_payload(
        "2026-09-20", "2026-09-20T12:00:00Z", "2026-09-20T13:00:00Z", 100
    )
    payload["multiAreaEntries"].append(
        {
            "deliveryStart": "2026-09-20T14:00:00Z",
            "deliveryEnd": "2026-09-20T15:00:00Z",
            "entryPerArea": {"SE3": 200},
        }
    )
    assert normalize_prices(payload, "SE3", NOW)["next_price_per_kwh"] is None
