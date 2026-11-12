"""Read-only RouterOS resource polling over authenticated HTTPS REST."""

from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

HOSTNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")


@dataclass(frozen=True)
class RouterResources:
    cpu_load_percent: float
    memory_used_percent: float


def _resource_url(host: str) -> str:
    """Allow only a hostname/IP and optional port, never a path or credentials."""
    raw = host.strip()
    if not raw or any(ch in raw for ch in "/?#@\\"):
        raise ValueError("Router host must be a hostname or IP address")
    parsed = urlsplit(f"https://{raw}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid router port") from exc
    if port == 0:
        raise ValueError("Invalid router port")
    hostname = parsed.hostname or ""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        if not HOSTNAME.fullmatch(hostname) or ".." in hostname:
            raise ValueError("Invalid router hostname") from None
    suffix = f":{port}" if port is not None else ""
    authority = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{authority}{suffix}/rest/system/resource"


def parse_resources(payload: object) -> RouterResources:
    row = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(row, dict):
        raise TypeError("RouterOS resource response must be an object")
    try:
        cpu = float(row["cpu-load"])
        total = float(row["total-memory"])
        free = float(row["free-memory"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "RouterOS resource response is missing numeric readings"
        ) from exc
    if not all(math.isfinite(value) for value in (cpu, total, free)):
        raise ValueError("RouterOS resource response has non-finite readings")
    if not 0 <= cpu <= 100 or total <= 0 or not 0 <= free <= total:
        raise ValueError("RouterOS resource response has out-of-range readings")
    return RouterResources(cpu, round(100 * (total - free) / total, 2))


async def fetch_resources(
    host: str,
    username: str,
    password: str,
    *,
    ca_bundle_path: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RouterResources:
    if not username or not password:
        raise ValueError("RouterOS username and password are required")
    url = _resource_url(host)
    async with httpx.AsyncClient(
        timeout=8.0,
        auth=(username, password),
        verify=ca_bundle_path or True,
        transport=transport,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return parse_resources(response.json())
