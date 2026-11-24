from __future__ import annotations

import asyncio
import ipaddress
import math
import socket
from collections.abc import Mapping
from typing import Any

import httpx

LATEST_PATH = "/air-data/latest"
CONNECT_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_SECONDS = 4.0

METRIC_NAMES = {
    "temp": "temperature",
    "humid": "humidity",
    "abs_humid": "absolute_humidity",
}
ALLOWED_METRICS = {
    "timestamp", "score", "dew_point", "temp", "humid", "abs_humid",
    "co2", "co2_est", "co2_est_baseline", "voc", "voc_baseline",
    "voc_h2_raw", "voc_ethanol_raw", "pm25", "pm10_est",
}
METRIC_RANGES = {
    "score": (0, 100),
    "temp": (-40, 125),
    "dew_point": (-100, 100),
    "humid": (0, 100),
    "abs_humid": (0, 1000),
    "co2": (0, 1_000_000),
    "co2_est": (0, 1_000_000),
    "co2_est_baseline": (0, 2**31),
    "voc": (0, 10_000_000),
    "voc_baseline": (0, 2**31),
    "voc_h2_raw": (0, 2**31),
    "voc_ethanol_raw": (0, 2**31),
    "pm25": (0, 1_000_000),
    "pm10_est": (0, 1_000_000),
}


class AwairTransportError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_allowed_local_address(value: str) -> bool:
    address = ipaddress.ip_address(value)
    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address in ipaddress.ip_network("10.0.0.0/8") or address in ipaddress.ip_network(
            "172.16.0.0/12"
        ) or address in ipaddress.ip_network("192.168.0.0/16") or address.is_link_local
    return address in ipaddress.ip_network("fc00::/7") or address.is_link_local


async def resolve_local_host(host: str) -> str:
    candidate = host.strip().strip("[]")
    if not candidate or any(token in candidate for token in ("/", "@", "#", "?", "%")):
        raise AwairTransportError("invalid_host")
    try:
        address = ipaddress.ip_address(candidate)
        addresses = [str(address)]
    except ValueError:
        try:
            records = await asyncio.wait_for(
                asyncio.get_running_loop().getaddrinfo(
                    candidate, 80, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
                ),
                timeout=3.0,
            )
        except (OSError, TimeoutError) as exc:
            raise AwairTransportError("host_resolution_failed") from exc
        addresses = sorted({str(record[4][0]) for record in records})
    if not addresses or any(not _is_allowed_local_address(value) for value in addresses):
        raise AwairTransportError("non_local_address")
    return addresses[0]


def normalize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AwairTransportError("invalid_response")
    result: dict[str, Any] = {}
    for key in ALLOWED_METRICS:
        if key not in payload:
            continue
        value = payload[key]
        if key == "timestamp":
            if isinstance(value, str) and len(value) <= 64:
                result[key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AwairTransportError("invalid_response")
        number = float(value)
        if not math.isfinite(number):
            raise AwairTransportError("invalid_response")
        minimum, maximum = METRIC_RANGES[key]
        if not minimum <= number <= maximum:
            raise AwairTransportError("invalid_response")
        result[METRIC_NAMES.get(key, key)] = value
    if not any(key in result for key in ("score", "temperature", "co2", "pm25", "voc")):
        raise AwairTransportError("invalid_response")
    return result


class AwairLocalClient:
    """Pinned-address, redirect-free adapter for Awair's read-only local HTTP API."""

    def __init__(
        self,
        *,
        configured_host: str,
        resolved_host: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.configured_host = configured_host
        self.resolved_host = resolved_host
        resolved_address = ipaddress.ip_address(resolved_host)
        self._url_host = f"[{resolved_host}]" if resolved_address.version == 6 else resolved_host
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
            follow_redirects=False,
            trust_env=False,
            headers={"Host": configured_host, "Accept": "application/json"},
        )

    @classmethod
    async def connect(
        cls,
        host: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AwairLocalClient:
        resolved = await resolve_local_host(host)
        client = cls(configured_host=host, resolved_host=resolved, transport=transport)
        try:
            await client.latest()
        except Exception:
            await client.close()
            raise
        return client

    async def latest(self) -> dict[str, Any]:
        try:
            response = await self._client.get(f"http://{self._url_host}{LATEST_PATH}")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise AwairTransportError("unreachable") from exc
        if 300 <= response.status_code < 400:
            raise AwairTransportError("redirect_rejected")
        if response.status_code != 200:
            raise AwairTransportError("http_error")
        try:
            return normalize_payload(response.json())
        except (ValueError, TypeError) as exc:
            raise AwairTransportError("invalid_response") from exc

    async def close(self) -> None:
        await self._client.aclose()


def fake_awair_transport(payload: Mapping[str, Any], *, status_code: int = 200) -> httpx.MockTransport:
    """Deterministic test transport. It never opens a socket or performs discovery."""
    frozen = dict(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET" or request.url.path != LATEST_PATH:
            return httpx.Response(404, json={"error": "not_found"})
        return httpx.Response(status_code, json=frozen)

    return httpx.MockTransport(handler)
