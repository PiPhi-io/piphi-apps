"""Platform-neutral, authenticated client for the PiPhi BLE gateway v1 API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from .bthome import BTHOME_UUID

SCHEMA_VERSION = "piphi.ble.observation.v1"
MAX_DATA_ITEMS = 32
MAX_DATA_HEX_CHARS = 510
MAX_DATA_BYTES = 512
MAX_PAGE_LIMIT = 256


class GatewayError(RuntimeError):
    """Gateway transport, authentication, or contract failure."""


class SequenceGap(GatewayError):
    """The gateway stream skipped a sequence and requires snapshot resync."""


def _bounded_hex_map(value: Any, field: str) -> dict[str, bytes]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_DATA_ITEMS:
        raise GatewayError(f"invalid {field}")
    result: dict[str, bytes] = {}
    used = 0
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, str) or len(raw) > MAX_DATA_HEX_CHARS:
            raise GatewayError(f"invalid {field}")
        try:
            decoded = bytes.fromhex(raw)
        except ValueError as exc:
            raise GatewayError(f"invalid {field}") from exc
        used += len(decoded)
        if used > MAX_DATA_BYTES:
            raise GatewayError(f"invalid {field}")
        result[key.lower()] = decoded
    return result


@dataclass(frozen=True)
class Observation:
    sequence: int
    device_handle: str
    receiver_id: str
    receiver_kind: str
    observed_monotonic_ms: int
    ingested_at: str
    replayed: bool
    rssi: int
    tx_power: int | None
    connectable: bool
    address_type: str
    service_uuids: tuple[str, ...]
    manufacturer_data: dict[str, bytes]
    service_data: dict[str, bytes]

    @classmethod
    def from_json(cls, value: Any) -> "Observation":
        if not isinstance(value, dict) or value.get("schema_version", value.get("schema")) != SCHEMA_VERSION:
            raise GatewayError("unsupported BLE observation schema")
        sequence = value.get("sequence")
        observed = value.get("observed_monotonic_ms")
        rssi = value.get("rssi")
        handle = value.get("device_handle")
        receiver_id = value.get("receiver_id")
        receiver_kind = value.get("receiver_kind")
        ingested_at = value.get("ingested_at")
        uuids = value.get("service_uuids", [])
        if not isinstance(sequence, int) or sequence < 0 or not isinstance(observed, int) or observed < 0:
            raise GatewayError("invalid observation ordering")
        if not isinstance(rssi, int) or not -127 <= rssi <= 20:
            raise GatewayError("invalid observation RSSI")
        if not all(isinstance(item, str) and len(item) <= 64 for item in (handle, receiver_id, receiver_kind, ingested_at)):
            raise GatewayError("invalid observation identity")
        try:
            if datetime.fromisoformat(ingested_at.replace("Z", "+00:00")).tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise GatewayError("invalid observation ingest timestamp") from exc
        if not isinstance(uuids, list) or len(uuids) > 32 or not all(isinstance(item, str) for item in uuids):
            raise GatewayError("invalid service UUIDs")
        tx_power = value.get("tx_power")
        if tx_power is not None and (not isinstance(tx_power, int) or not -127 <= tx_power <= 127):
            raise GatewayError("invalid tx_power")
        return cls(
            sequence=sequence,
            device_handle=handle,
            receiver_id=receiver_id,
            receiver_kind=receiver_kind,
            observed_monotonic_ms=observed,
            ingested_at=ingested_at,
            replayed=value.get("replayed") is True,
            rssi=rssi,
            tx_power=tx_power,
            connectable=value.get("connectable") is True,
            address_type=str(value.get("address_type", "unknown"))[:32],
            service_uuids=tuple(item.lower() for item in uuids),
            manufacturer_data=_bounded_hex_map(value.get("manufacturer_data"), "manufacturer_data"),
            service_data=_bounded_hex_map(value.get("service_data"), "service_data"),
        )


@dataclass(frozen=True)
class ObservationPage:
    observations: tuple[Observation, ...]
    cursor: int
    receiver_healthy: bool
    malformed_count: int = 0
    gap: bool = False


class GatewayClient:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 10, transport=None) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GatewayError("BLE gateway unavailable") from exc
        if response.status_code in {401, 403}:
            raise GatewayError("BLE gateway authentication rejected")
        if response.status_code == 409:
            raise SequenceGap("BLE observation cursor gap")
        if response.is_error:
            raise GatewayError(f"BLE gateway returned HTTP {response.status_code}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise GatewayError("BLE gateway returned invalid JSON") from exc

    async def register(self, consumer_id: str, device_handle: str) -> None:
        await self._request(
            "PUT",
            f"/v1/ble/consumers/{quote(consumer_id, safe='')}",
            json={
                "schema_version": "piphi.ble.consumer.v1",
                "matcher": {"device_handles": [device_handle], "service_uuids": [BTHOME_UUID]},
                "scan_mode": "passive",
                "queue_capacity": 128,
            },
        )

    async def unregister(self, consumer_id: str) -> None:
        await self._request("DELETE", f"/v1/ble/consumers/{quote(consumer_id, safe='')}")

    async def observations(self, consumer_id: str, *, after: int, limit: int = 128) -> ObservationPage:
        raw = await self._request(
            "GET",
            f"/v1/ble/observations/{quote(consumer_id, safe='')}",
            params={"after": after, "limit": min(max(limit, 1), MAX_PAGE_LIMIT)},
        )
        return self._page(raw, after)

    async def snapshot(self, consumer_id: str, *, after: int = 0) -> ObservationPage:
        raw = await self._request("GET", f"/v1/ble/snapshot/{quote(consumer_id, safe='')}")
        # Snapshots replace state and may legitimately contain the latest value
        # at or before the stream cursor supplied by the caller.
        return self._page(raw, -1)

    @staticmethod
    def _page(raw: Any, after: int) -> ObservationPage:
        if isinstance(raw, list):
            items, metadata = raw, {}
        elif isinstance(raw, dict):
            items, metadata = raw.get("observations", []), raw
        else:
            raise GatewayError("invalid BLE gateway page")
        if not isinstance(items, list) or len(items) > MAX_PAGE_LIMIT:
            raise GatewayError("invalid BLE gateway page")
        parsed: list[Observation] = []
        malformed_count = 0
        for item in items:
            try:
                parsed.append(Observation.from_json(item))
            except GatewayError:
                malformed_count += 1
        observations = tuple(parsed)
        sequences = [item.sequence for item in observations]
        if sequences != sorted(set(sequences)) or any(sequence <= after for sequence in sequences):
            raise GatewayError("unordered BLE observation page")
        cursor = metadata.get("cursor", sequences[-1] if sequences else after)
        if not isinstance(cursor, int) or cursor < (sequences[-1] if sequences else after):
            raise GatewayError("invalid BLE observation cursor")
        return ObservationPage(observations, cursor, metadata.get("receiver_healthy") is True, malformed_count, metadata.get("gap") is True)
