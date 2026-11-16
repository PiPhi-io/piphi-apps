"""Read-only Octopus Energy electricity tariff rates.

The API endpoint and payload shape follow Octopus Energy's public REST API.
Only caller-selected product/tariff identifiers are interpolated into a fixed
HTTPS origin; arbitrary URLs and account credentials are never used here.
"""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

API_ORIGIN = "https://api.octopus.energy"
CODE = re.compile(r"[A-Z0-9-]{3,80}\Z")
MAX_PAGES = 3
MAX_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class TariffRates:
    current_p_kwh: float
    next_p_kwh: float | None
    current_valid_to: str | None
    current_valid_from: str | None = None
    next_valid_from: str | None = None
    next_valid_to: str | None = None
    fetched_at: str | None = None


def _instant(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def parse_rates(payload: Any, *, now: datetime) -> TariffRates:
    """Select the active and next rate, independent of provider result order."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise TypeError("Octopus rates response has no results")
    parsed: list[tuple[datetime, datetime | None, float, str | None]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = _instant(row.get("valid_from"))
        end = _instant(row.get("valid_to"))
        try:
            price = float(row.get("value_inc_vat"))
        except (TypeError, ValueError):
            continue
        method = row.get("payment_method")
        if (
            start is None
            or not math.isfinite(price)
            or method not in (None, "DIRECT_DEBIT")
        ):
            continue
        parsed.append((start, end, price, method))
    current = sorted(
        (row for row in parsed if row[0] <= now and (row[1] is None or now < row[1])),
        key=lambda row: (row[3] == "DIRECT_DEBIT", row[0]),
        reverse=True,
    )
    if not current:
        raise ValueError("No current direct-debit tariff rate was returned")
    next_rows = sorted(
        (row for row in parsed if row[0] > now),
        key=lambda row: (row[0], row[3] != "DIRECT_DEBIT"),
    )
    active = current[0]
    return TariffRates(
        current_p_kwh=active[2],
        next_p_kwh=next_rows[0][2] if next_rows else None,
        current_valid_to=active[1].isoformat() if active[1] else None,
        current_valid_from=active[0].isoformat(),
        next_valid_from=next_rows[0][0].isoformat() if next_rows else None,
        next_valid_to=(
            next_rows[0][1].isoformat()
            if next_rows and next_rows[0][1] is not None
            else None
        ),
        fetched_at=now.astimezone(UTC).isoformat(),
    )


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return min(MAX_RETRY_DELAY_SECONDS, max(0.0, float(retry_after)))
        except ValueError:
            pass
    return min(MAX_RETRY_DELAY_SECONDS, 0.1 * (2**attempt))


async def _get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, object] | None = None,
) -> httpx.Response:
    for attempt in range(MAX_RETRIES):
        try:
            response = await client.get(url, params=params)
        except (httpx.TimeoutException, httpx.NetworkError):
            if attempt + 1 == MAX_RETRIES:
                raise
            await asyncio.sleep(min(MAX_RETRY_DELAY_SECONDS, 0.1 * (2**attempt)))
            continue
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt + 1 == MAX_RETRIES:
            return response
        await asyncio.sleep(_retry_delay(response, attempt))
    raise AssertionError("unreachable")


async def fetch_rates(
    product_code: str,
    tariff_code: str,
    *,
    now: datetime | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> TariffRates:
    product = product_code.strip().upper()
    tariff = tariff_code.strip().upper()
    if not CODE.fullmatch(product) or not CODE.fullmatch(tariff):
        raise ValueError("Invalid Octopus product or tariff code")
    instant = now or datetime.now(UTC)
    start = instant - timedelta(hours=1)
    end = instant + timedelta(hours=25)
    url = (
        f"{API_ORIGIN}/v1/products/{product}/electricity-tariffs/"
        f"{tariff}/standard-unit-rates/"
    )
    async with httpx.AsyncClient(timeout=8.0, transport=transport) as client:
        params = {
            "period_from": start.isoformat(),
            "period_to": end.isoformat(),
            "page_size": 100,
        }
        results: list[Any] = []
        next_url: str | None = url
        seen: set[str] = set()
        for page_number in range(MAX_PAGES):
            if next_url in seen:
                raise ValueError("Octopus pagination loop detected")
            seen.add(next_url)
            response = await _get_with_retries(
                client, next_url, params=params if page_number == 0 else None
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise TypeError("Octopus rates response has no results")
            results.extend(payload["results"])
            candidate = payload.get("next")
            if candidate is None:
                next_url = None
                break
            if not isinstance(candidate, str):
                raise ValueError("Invalid Octopus pagination link")
            parsed_next = httpx.URL(candidate)
            if (
                parsed_next.scheme != "https"
                or parsed_next.host != "api.octopus.energy"
                or parsed_next.path != httpx.URL(url).path
                or parsed_next.params.get("period_from") != start.isoformat()
                or parsed_next.params.get("period_to") != end.isoformat()
                or parsed_next.params.get("page_size") != "100"
            ):
                raise ValueError("Unsafe Octopus pagination link")
            next_url = candidate
        if next_url is not None:
            raise ValueError(f"Octopus response exceeded {MAX_PAGES} pages")
        return parse_rates({"results": results}, now=instant)
