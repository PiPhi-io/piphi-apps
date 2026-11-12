"""A small, explicit manual pickup schedule while provider adapters remain planned."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class NextPickup:
    collection_type: str
    collection_date: str
    days_until_collection: int


def resolve_manual_pickup(
    collection_date: str,
    collection_type: str,
    schedule_timezone: str = "UTC",
    *,
    now: datetime | None = None,
) -> NextPickup:
    """Return a current pickup only when the configured date is valid and upcoming."""
    kind = collection_type.strip()
    if not kind or len(kind) > 60:
        raise ValueError("Collection type must be 1–60 characters")
    try:
        zone = ZoneInfo(schedule_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown schedule timezone") from exc
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", collection_date):
            raise ValueError("Invalid date format")
        pickup = date.fromisoformat(collection_date)
    except (TypeError, ValueError) as exc:
        raise ValueError("Collection date must use YYYY-MM-DD") from exc
    today = now.astimezone(zone).date() if now else datetime.now(zone).date()
    days = (pickup - today).days
    if days < 0:
        raise ValueError("The configured pickup date has passed")
    return NextPickup(kind, pickup.isoformat(), days)
