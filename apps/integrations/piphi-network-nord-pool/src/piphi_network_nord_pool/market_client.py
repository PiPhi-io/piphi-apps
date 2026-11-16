"""Read published day-ahead prices from Nord Pool's public data portal."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .pricing import normalize_prices

API_URL = "https://dataportal-api.nordpoolgroup.com/api/DayAheadPrices"
ENDPOINT_STATUS = "first_party_public_portal_backend_unofficial_api"
LICENSING_STATUS = "redistribution_rights_unresolved"
PRODUCTION_PUBLICATION_ALLOWED = False
MARKET_TIMEZONE = ZoneInfo("Europe/Oslo")
MAX_RESPONSE_BYTES = 1_000_000
MAX_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 2.0


class MarketDataError(Exception):
    """The market feed did not provide a usable current price."""


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(MAX_RETRY_DELAY_SECONDS, 0.1 * (2**attempt))


async def _get_with_retries(
    client: httpx.AsyncClient, *, params: dict[str, str]
) -> httpx.Response:
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(API_URL, params=params)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt + 1 == MAX_RETRIES:
                raise MarketDataError("market data request failed") from exc
            await asyncio.sleep(min(MAX_RETRY_DELAY_SECONDS, 0.1 * (2**attempt)))
            continue
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt + 1 == MAX_RETRIES:
            return response
        await asyncio.sleep(_retry_delay(response, attempt))
    raise AssertionError("unreachable")


async def fetch_day(
    client: httpx.AsyncClient,
    *,
    day: str,
    area: str,
    currency: str,
) -> dict[str, Any] | None:
    try:
        response = await _get_with_retries(
            client,
            params={
                "date": day,
                "market": "DayAhead",
                "deliveryArea": area,
                "currency": currency,
            },
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise MarketDataError("market response too large")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise MarketDataError("market data request failed") from exc
    if not isinstance(payload, dict):
        raise MarketDataError("market response must be an object")
    if payload.get("deliveryDateCET") not in (None, day):
        raise MarketDataError("market response date mismatch")
    return payload


async def fetch_prices(
    *,
    area: str,
    currency: str,
    now: datetime,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch today's prices and tomorrow's when published, without fabricating gaps."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    market_day = now.astimezone(MARKET_TIMEZONE).date()
    async with httpx.AsyncClient(timeout=8.0, transport=transport) as client:
        today = await fetch_day(
            client, day=market_day.isoformat(), area=area, currency=currency
        )
        if today is None:
            raise MarketDataError("current market day is unavailable")
        combined = dict(today)
        tomorrow_day = (market_day + timedelta(days=1)).isoformat()
        try:
            tomorrow = await fetch_day(
                client, day=tomorrow_day, area=area, currency=currency
            )
        except MarketDataError:
            tomorrow = None
        if tomorrow is not None and tomorrow.get("currency") == today.get("currency"):
            tomorrow_entries = tomorrow.get("multiAreaEntries")
            today_entries = today.get("multiAreaEntries")
            if isinstance(today_entries, list) and isinstance(tomorrow_entries, list):
                combined["multiAreaEntries"] = today_entries + tomorrow_entries
        try:
            normalized = normalize_prices(combined, area, now)
        except ValueError as exc:
            raise MarketDataError(str(exc)) from exc
        if normalized["current_price_per_kwh"] is None:
            raise MarketDataError("no current price interval")
        if normalized["currency"] != currency:
            raise MarketDataError("market response currency mismatch")
        normalized["data_updated_at"] = today.get("updatedAt")
        normalized["fetched_at"] = datetime.now(UTC).isoformat()
        normalized["source_endpoint_status"] = ENDPOINT_STATUS
        normalized["source_licensing_status"] = LICENSING_STATUS
        normalized["production_publication_allowed"] = PRODUCTION_PUBLICATION_ALLOWED
        return normalized
