from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

MAX_DATA_ITEMS = 32
MAX_DATA_BYTES = 512


class GatewayError(RuntimeError):
    """A sanitized gateway failure safe to surface in diagnostics."""


class CursorGap(GatewayError):
    pass


def _bounded_hex_map(value: object, field: str) -> dict[str, bytes]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > MAX_DATA_ITEMS:
        raise GatewayError(f"invalid {field}")
    result: dict[str, bytes] = {}
    used = 0
    for key, raw in value.items():
        if not isinstance(key, str) or not isinstance(raw, str):
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


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise GatewayError("invalid ingested_at")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise GatewayError("invalid ingested_at") from exc
    if result.tzinfo is None:
        raise GatewayError("ingested_at must include a timezone")
    return result.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Observation:
    sequence: int
    device_handle: str
    receiver_id: str
    receiver_kind: str
    observed_monotonic_ms: int
    ingested_at: datetime
    replayed: bool
    rssi: int
    tx_power: int | None
    connectable: bool
    address_type: str
    service_uuids: tuple[str, ...]
    manufacturer_data: dict[str, bytes]
    service_data: dict[str, bytes]

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> Observation:
        if raw.get("schema_version", raw.get("schema")) != "piphi.ble.observation.v1":
            raise GatewayError("unsupported observation schema")
        handle = raw.get("device_handle")
        receiver = raw.get("receiver_id")
        if not isinstance(handle, str) or not handle or len(handle) > 256:
            raise GatewayError("invalid device_handle")
        if not isinstance(receiver, str) or not receiver or len(receiver) > 256:
            raise GatewayError("invalid receiver_id")
        rssi = raw.get("rssi")
        tx_power = raw.get("tx_power")
        if not isinstance(rssi, int) or isinstance(rssi, bool) or not -127 <= rssi <= 20:
            raise GatewayError("invalid rssi")
        if tx_power is not None and (not isinstance(tx_power, int) or isinstance(tx_power, bool) or not -127 <= tx_power <= 40):
            raise GatewayError("invalid tx_power")
        uuids = raw.get("service_uuids", [])
        if not isinstance(uuids, list) or len(uuids) > 64 or not all(isinstance(v, str) and len(v) <= 64 for v in uuids):
            raise GatewayError("invalid service_uuids")
        return cls(
            sequence=int(raw["sequence"]),
            device_handle=handle,
            receiver_id=receiver,
            receiver_kind=str(raw.get("receiver_kind", "unknown"))[:64],
            observed_monotonic_ms=int(raw["observed_monotonic_ms"]),
            ingested_at=_utc(raw.get("ingested_at")),
            replayed=bool(raw.get("replayed", False)),
            rssi=rssi,
            tx_power=tx_power,
            connectable=bool(raw.get("connectable", False)),
            address_type=str(raw.get("address_type", "unknown"))[:32],
            service_uuids=tuple(uuids),
            manufacturer_data=_bounded_hex_map(raw.get("manufacturer_data"), "manufacturer_data"),
            service_data=_bounded_hex_map(raw.get("service_data"), "service_data"),
        )


@dataclass(frozen=True, slots=True)
class ObservationPage:
    observations: tuple[Observation, ...]
    cursor: int
    gap: bool = False
    receiver_healthy: bool = False


class BleGatewayClient:
    """Authenticated async client for the PiPhi BLE gateway v1 consumer API."""

    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def register(self, consumer_id: str, device_handles: list[str]) -> None:
        await self._request("PUT", f"/v1/ble/consumers/{quote(consumer_id, safe='')}", json={
            "schema_version": "piphi.ble.consumer.v1",
            "matcher": {"device_handles": device_handles},
            "scan_mode": "passive",
            "queue_capacity": 256,
        })

    async def unregister(self, consumer_id: str) -> None:
        await self._request("DELETE", f"/v1/ble/consumers/{quote(consumer_id, safe='')}")

    async def observations(self, consumer_id: str, *, after: int, limit: int = 256) -> ObservationPage:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        payload = await self._request(
            "GET", f"/v1/ble/observations/{quote(consumer_id, safe='')}", params={"after": after, "limit": limit},
        )
        if bool(payload.get("gap")):
            raise CursorGap("observation cursor gap")
        rows = payload.get("observations", payload.get("items", []))
        if not isinstance(rows, list):
            raise GatewayError("invalid observations response")
        observations = tuple(Observation.from_payload(row) for row in rows if isinstance(row, dict))
        cursor = int(payload.get("cursor", observations[-1].sequence if observations else after))
        return ObservationPage(observations, cursor, receiver_healthy=payload.get("receiver_healthy") is True)

    async def snapshot(self, consumer_id: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/v1/ble/snapshot/{quote(consumer_id, safe='')}")
        if not isinstance(payload, dict):
            raise GatewayError("invalid snapshot response")
        return payload

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GatewayError(f"gateway transport failure ({type(exc).__name__})") from exc
        if response.status_code == 409:
            raise CursorGap("observation cursor gap")
        if response.status_code in (401, 403):
            raise GatewayError("gateway authentication failed")
        if response.is_error:
            raise GatewayError(f"gateway returned HTTP {response.status_code}")
        if response.status_code == 204 or not response.content:
            return {}
        try:
            value = response.json()
        except ValueError as exc:
            raise GatewayError("gateway returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise GatewayError("gateway returned invalid response")
        return value
