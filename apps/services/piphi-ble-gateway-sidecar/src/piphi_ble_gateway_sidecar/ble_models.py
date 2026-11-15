from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

SCHEMA_VERSION = "piphi.ble.observation.v1"
MAX_DATA_FIELDS = 32
MAX_DATA_BYTES = 512


@dataclass(frozen=True, slots=True)
class Advertisement:
    """Backend-neutral scanner input. Raw identity never leaves the manager."""

    address: str
    observed_monotonic_ms: int
    rssi: int
    tx_power: int | None = None
    connectable: bool = False
    address_type: str = "unknown"
    service_uuids: tuple[str, ...] = ()
    manufacturer_data: dict[int, bytes] = field(default_factory=dict)
    service_data: dict[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Matcher:
    device_handles: frozenset[str] = frozenset()
    manufacturer_ids: frozenset[int] = frozenset()
    service_uuids: frozenset[str] = frozenset()

    @property
    def bounded(self) -> bool:
        return bool(self.device_handles or self.manufacturer_ids or self.service_uuids)

    def matches(self, handle: str, advert: Advertisement | None, observation: dict | None = None) -> bool:
        manufacturer_ids = set(advert.manufacturer_data) if advert else {
            int(key, 16) for key in (observation or {}).get("manufacturer_data", {})
        }
        service_uuids = set(advert.service_uuids) | set(advert.service_data) if advert else set(
            (observation or {}).get("service_uuids", [])
        ) | set((observation or {}).get("service_data", {}))
        # Categories are conjunctive so a protocol UUID cannot broaden an
        # explicitly selected opaque-device scope.
        return (
            (not self.device_handles or handle in self.device_handles)
            and (not self.manufacturer_ids or bool(self.manufacturer_ids & manufacturer_ids))
            and (not self.service_uuids or bool(self.service_uuids & service_uuids))
        )


ScanMode = Literal["auto", "active", "passive"]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def bounded_hex_map(values: dict[int | str, bytes], *, numeric_keys: bool = False) -> dict[str, str]:
    result: dict[str, str] = {}
    used = 0
    for key, value in sorted(values.items(), key=lambda item: str(item[0])):
        if len(result) >= MAX_DATA_FIELDS:
            break
        remaining = MAX_DATA_BYTES - used
        if remaining <= 0:
            break
        chunk = bytes(value[:remaining])
        normalized_key = f"{int(key):04x}" if numeric_keys else str(key).lower()
        result[normalized_key] = chunk.hex()
        used += len(chunk)
    return result
