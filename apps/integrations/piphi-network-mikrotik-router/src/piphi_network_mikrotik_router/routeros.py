"""Read-only RouterOS resource polling over authenticated HTTPS REST."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

HOSTNAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")
MAX_RESPONSE_BYTES = 262_144
MAX_ENDPOINT_CONCURRENCY = 2


@dataclass(frozen=True)
class RouterResources:
    cpu_load_percent: float
    memory_used_percent: float
    appliance_identifier: str = ""
    routeros_version: str | None = None


class RouterOSError(RuntimeError):
    """Credential-free, classified RouterOS failure."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


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


def _license_url(host: str) -> str:
    return _resource_url(host).removesuffix("resource") + "license"


def parse_resources(payload: object) -> RouterResources:
    if isinstance(payload, list) and len(payload) != 1:
        raise ValueError("RouterOS resource response must contain exactly one row")
    row = payload[0] if isinstance(payload, list) else payload
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
        endpoint_slots = asyncio.Semaphore(MAX_ENDPOINT_CONCURRENCY)
        try:
            resource_payload, license_payload = await asyncio.gather(
                _bounded_json(client, url, endpoint_slots),
                _bounded_json(client, _license_url(host), endpoint_slots),
            )
            resources = parse_resources(resource_payload)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                raise RouterOSError("authentication_failed", retryable=False) from exc
            if status == 403:
                raise RouterOSError("permission_denied", retryable=False) from exc
            if status == 404:
                raise RouterOSError(
                    "routeros_rest_unsupported", retryable=False
                ) from exc
            if status == 429:
                raise RouterOSError("rate_limited", retryable=True) from exc
            raise RouterOSError(
                "routeros_server_error"
                if status >= 500
                else "routeros_request_rejected",
                retryable=status >= 500,
            ) from exc
        except httpx.TimeoutException as exc:
            raise RouterOSError("connection_timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            reason = (
                "tls_validation_failed"
                if "certificate" in str(exc).casefold()
                else "connection_failed"
            )
            raise RouterOSError(
                reason, retryable=reason == "connection_failed"
            ) from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RouterOSError("invalid_routeros_response", retryable=False) from exc

        license_row = (
            license_payload[0]
            if isinstance(license_payload, list) and license_payload
            else license_payload
        )
        if not isinstance(license_row, dict):
            raise RouterOSError("invalid_routeros_identity", retryable=False)
        software_id = str(license_row.get("software-id") or "").strip()
        if not software_id or len(software_id) > 128:
            raise RouterOSError("missing_routeros_identity", retryable=False)
        resource_row = resource_payload
        resource_row = (
            resource_row[0]
            if isinstance(resource_row, list) and resource_row
            else resource_row
        )
        version = (
            resource_row.get("version") if isinstance(resource_row, dict) else None
        )
        major_match = re.match(r"^(\d+)(?:\.|$)", str(version or ""))
        if major_match is None or int(major_match.group(1)) != 7:
            raise RouterOSError("unsupported_routeros_version", retryable=False)
        return RouterResources(
            resources.cpu_load_percent,
            resources.memory_used_percent,
            appliance_identifier=software_id,
            routeros_version=str(version) if version else None,
        )


async def _bounded_json(
    client: httpx.AsyncClient, url: str, endpoint_slots: asyncio.Semaphore
) -> object:
    response: httpx.Response | None = None
    try:
        async with endpoint_slots:
            response = await client.send(client.build_request("GET", url), stream=True)
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    if int(declared) > MAX_RESPONSE_BYTES:
                        raise RouterOSError(
                            "response_size_limit_exceeded", retryable=False
                        )
                except ValueError as exc:
                    raise RouterOSError("invalid_content_length", retryable=False) from exc
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RouterOSError(
                        "response_size_limit_exceeded", retryable=False
                    )
        return json.loads(body)
    finally:
        if response is not None:
            await response.aclose()
