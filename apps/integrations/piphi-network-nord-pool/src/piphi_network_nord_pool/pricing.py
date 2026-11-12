"""Normalize Nord Pool day-ahead intervals for PiPhi state and telemetry."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


def normalize_prices(payload: dict[str, Any], area: str, now: datetime) -> dict[str, Any]:
    """Return only validated, area-specific prices; API prices are per MWh."""
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    currency = payload.get("currency")
    if not isinstance(currency, str) or not currency.isalpha() or len(currency) != 3:
        raise ValueError("invalid currency")
    entries = payload.get("multiAreaEntries")
    if not isinstance(entries, list):
        raise ValueError("missing price intervals")

    intervals: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        prices = entry.get("entryPerArea")
        if not isinstance(prices, dict) or area not in prices:
            continue
        try:
            start = datetime.fromisoformat(str(entry["deliveryStart"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(entry["deliveryEnd"]).replace("Z", "+00:00"))
            if isinstance(prices[area], bool):
                raise ValueError("invalid price")
            price = float(prices[area])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid price interval") from exc
        if start.tzinfo is None or end.tzinfo is None or end <= start or not isfinite(price):
            raise ValueError("invalid price interval")
        intervals.append(
            {
                "start": start.astimezone(timezone.utc).isoformat(),
                "end": end.astimezone(timezone.utc).isoformat(),
                "price_per_kwh": price / 1000,
            }
        )

    intervals.sort(key=lambda item: item["start"])
    if not intervals:
        raise ValueError("no prices for selected market area")
    for previous, following in zip(intervals, intervals[1:]):
        if previous["end"] > following["start"]:
            raise ValueError("overlapping price intervals")

    current_index = next(
        (
            index
            for index, interval in enumerate(intervals)
            if datetime.fromisoformat(interval["start"]) <= now < datetime.fromisoformat(interval["end"])
        ),
        None,
    )
    current = intervals[current_index] if current_index is not None else None
    next_interval = (
        intervals[current_index + 1]
        if current_index is not None and current_index + 1 < len(intervals)
        else None
    )
    if current is not None and next_interval is not None and current["end"] != next_interval["start"]:
        next_interval = None
    return {
        "market_area": area,
        "currency": currency.upper(),
        "price_unit": f"{currency.upper()}/kWh",
        "current_price_per_kwh": current["price_per_kwh"] if current else None,
        "current_interval_start": current["start"] if current else None,
        "current_interval_end": current["end"] if current else None,
        "next_price_per_kwh": next_interval["price_per_kwh"] if next_interval else None,
        "next_interval_start": next_interval["start"] if next_interval else None,
        "next_interval_end": next_interval["end"] if next_interval else None,
        "chart_intervals": intervals,
    }
