from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


SenseApiCall = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class SenseApplianceDetails:
    device_id: str
    name: str
    icon: str
    device_type: str | None = None
    first_usage: str | None = None
    timeline_enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class SenseTimelineEvent:
    event_id: str
    occurred_at: str
    event_type: str
    body: str
    device_id: str | None = None
    device_name: str | None = None
    icon: str | None = None
    subtype: str | None = None


@dataclass(frozen=True, slots=True)
class ExtendedSenseSnapshot:
    appliances: tuple[SenseApplianceDetails, ...] = field(default_factory=tuple)
    always_on_power_w: float | None = None
    other_power_w: float | None = None
    timeline_events: tuple[SenseTimelineEvent, ...] = field(default_factory=tuple)


class SenseExtendedApi:
    """Best-effort access to useful read-only, undocumented Sense endpoints."""

    def __init__(self, api_call: SenseApiCall, *, monitor_id: str, user_id: str) -> None:
        self._api_call = api_call
        self._monitor_id = monitor_id
        self._user_id = user_id
        self._snapshot = ExtendedSenseSnapshot()

    @property
    def snapshot(self) -> ExtendedSenseSnapshot:
        return self._snapshot

    async def refresh(self, *, timeline_items: int = 20) -> ExtendedSenseSnapshot:
        appliances = await self._best_effort(
            f"app/monitors/{self._monitor_id}/devices",
            parser=_parse_appliances,
            fallback=self._snapshot.appliances,
        )
        always_on_power_w = await self._best_effort(
            f"app/monitors/{self._monitor_id}/devices/always_on",
            parser=_parse_power_w,
            fallback=self._snapshot.always_on_power_w,
        )
        other_power_w = await self._best_effort(
            f"app/monitors/{self._monitor_id}/devices/unknown",
            parser=_parse_power_w,
            fallback=self._snapshot.other_power_w,
        )
        timeline_events = await self._best_effort(
            f"users/{self._user_id}/timeline",
            payload={"n_items": max(1, min(timeline_items, 100))},
            parser=_parse_timeline,
            fallback=self._snapshot.timeline_events,
        )
        self._snapshot = ExtendedSenseSnapshot(
            appliances=appliances,
            always_on_power_w=always_on_power_w,
            other_power_w=other_power_w,
            timeline_events=timeline_events,
        )
        return self._snapshot

    async def get_appliance_details(self, device_id: str) -> SenseApplianceDetails | None:
        """Fetch one appliance without exposing unstable raw tags to Core."""
        data = await self._api_call(
            f"app/monitors/{self._monitor_id}/devices/{device_id}", {}
        )
        parsed = _parse_appliances(data)
        return parsed[0] if parsed else None

    async def _best_effort(self, endpoint, *, parser, fallback, payload=None):
        try:
            parsed = parser(await self._api_call(endpoint, payload or {}))
            return fallback if parsed is None else parsed
        except Exception:
            # Preserve the last good value when an unofficial endpoint changes.
            return fallback


def _parse_appliances(data: Any) -> tuple[SenseApplianceDetails, ...]:
    if isinstance(data, Mapping):
        if isinstance(data.get("devices"), list):
            entries = data["devices"]
        elif isinstance(data.get("device"), Mapping):
            entries = [data["device"]]
        elif "id" in data:
            entries = [data]
        else:
            entries = []
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError("unexpected Sense appliance response")

    appliances = []
    for entry in entries:
        if not isinstance(entry, Mapping) or entry.get("id") is None:
            continue
        tags = entry.get("tags") if isinstance(entry.get("tags"), Mapping) else {}
        appliances.append(
            SenseApplianceDetails(
                device_id=str(entry["id"]),
                name=str(entry.get("name") or tags.get("OriginalName") or entry["id"]),
                icon=str(entry.get("icon") or tags.get("Icon") or "unknown"),
                device_type=_optional_text(
                    tags.get("UserDeviceTypeDisplayString")
                    or tags.get("DefaultUserDeviceType")
                    or tags.get("Type")
                ),
                first_usage=_optional_text(tags.get("DateFirstUsage")),
                timeline_enabled=_optional_bool(
                    tags.get("TimelineAllowed", tags.get("TimelineDefault"))
                ),
            )
        )
    return tuple(appliances)


def _parse_power_w(data: Any) -> float | None:
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return float(data)
    if not isinstance(data, Mapping):
        return None
    for key in ("w", "watts", "power_w", "always_on", "unknown"):
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for key in ("device", "usage", "total"):
        nested = data.get(key)
        if isinstance(nested, Mapping):
            value = _parse_power_w(nested)
            if value is not None:
                return value
    return None


def _parse_timeline(data: Any) -> tuple[SenseTimelineEvent, ...]:
    if not isinstance(data, Mapping) or not isinstance(data.get("items"), list):
        raise ValueError("unexpected Sense timeline response")
    events = []
    for item in data["items"]:
        if not isinstance(item, Mapping):
            continue
        occurred_at = _optional_text(item.get("time"))
        event_type = _optional_text(item.get("type"))
        if not occurred_at or not event_type:
            continue
        body = str(item.get("body") or "").replace(
            "{device.name}", str(item.get("device_name") or "Device")
        )
        events.append(
            SenseTimelineEvent(
                event_id=str(item.get("guid") or f"{occurred_at}:{event_type}"),
                occurred_at=occurred_at,
                event_type=event_type,
                subtype=_optional_text(item.get("subtype")),
                body=body,
                device_id=_optional_text(item.get("device_id")),
                device_name=_optional_text(item.get("device_name")),
                icon=_optional_text(item.get("icon")),
            )
        )
    return tuple(events)


def _optional_text(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None
