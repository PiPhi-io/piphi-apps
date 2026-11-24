"""Bounded, read-only access to an OpenEPaperLink tag database."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")
MAX_PAGES = 32
MAX_TAGS = 4096
MAX_RESPONSE_BYTES = 1_048_576
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    )
)
DENIED_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("169.254.170.2"),
    ipaddress.ip_address("fd00:ec2::254"),
}
Resolver = Callable[[str, int], Awaitable[set[str]]]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class TagObservation:
    source_id: str
    pending_transfer_count: int


@dataclass(frozen=True)
class AccessPointSnapshot:
    tags: tuple[TagObservation, ...]

    @property
    def tag_count(self) -> int:
        return len(self.tags)

    @property
    def pending_transfer_count(self) -> int:
        return sum(tag.pending_transfer_count for tag in self.tags)


def _is_allowed_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address not in DENIED_METADATA_ADDRESSES and any(
        address in network for network in PRIVATE_NETWORKS
    )


def local_endpoint(host: str) -> tuple[str, int]:
    raw = host.strip().lower()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("Access point must be a local hostname or IP address")
    parsed = urlsplit(f"http://{raw}")
    try:
        port = parsed.port or 80
    except ValueError as exc:
        raise ValueError("Invalid access-point port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Invalid access-point port")
    name = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        if not LOCAL_NAME.fullmatch(name) or ".." in name or not name.endswith((".local", ".lan")):
            raise ValueError("Access point hostname must end in .local or .lan") from None
    else:
        if not _is_allowed_address(str(address)):
            raise ValueError("Access point must use an RFC1918, ULA, or link-local address")
    return name, port


def _ap_origin(host: str) -> str:
    name, port = local_endpoint(host)
    authority = f"[{name}]" if ":" in name else name
    return f"http://{authority}{f':{port}' if port != 80 else ''}"


async def _resolve(name: str, port: int) -> set[str]:
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        loop = asyncio.get_running_loop()
        records = await asyncio.wait_for(
            loop.getaddrinfo(name, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM),
            timeout=3.0,
        )
        return {str(record[4][0]) for record in records}
    return {str(address)}


def _source_id(tag: dict[str, object]) -> str:
    for key in ("mac", "MAC", "id"):
        value = tag.get(key)
        if isinstance(value, str) and re.fullmatch(r"[0-9A-Fa-f:-]{8,32}", value):
            return re.sub(r"[:-]", "", value).lower()
    raise ValueError("Access point returned a tag without a stable identifier")


async def fetch_snapshot(
    host: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = _resolve,
    sleep: Sleep = asyncio.sleep,
    attempts: int = 3,
) -> AccessPointSnapshot:
    """Read a bounded inventory while pinning DNS to an approved local address."""
    name, port = local_endpoint(host)
    if not 1 <= attempts <= 3:
        raise ValueError("attempts must be between one and three")
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            addresses = await resolver(name, port)
            if not addresses or any(not _is_allowed_address(value) for value in addresses):
                raise ValueError("Access point resolved outside the private local network")
            address = min(addresses)
            authority = f"[{address}]" if ":" in address else address
            origin = f"http://{authority}:{port}"
            host_header = f"[{name}]:{port}" if ":" in name else f"{name}:{port}"
            observations: dict[str, TagObservation] = {}
            position = 0
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0, connect=3.0),
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                for _ in range(MAX_PAGES):
                    response = await client.get(
                        f"{origin}/get_db",
                        params={"pos": position},
                        headers={"Host": host_header, "Accept": "application/json"},
                    )
                    if response.is_redirect:
                        raise ValueError("Access point redirects are not allowed")
                    response.raise_for_status()
                    if len(response.content) > MAX_RESPONSE_BYTES:
                        raise ValueError("Access point response exceeded the size limit")
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get("tags"), list):
                        raise TypeError("Access point returned an invalid tag page")
                    for raw_tag in payload["tags"]:
                        if not isinstance(raw_tag, dict):
                            raise TypeError("Access point returned an invalid tag record")
                        source_id = _source_id(raw_tag)
                        queued = raw_tag.get("pending", 0)
                        if type(queued) is not int or not 0 <= queued <= 1_000_000:
                            raise ValueError("Access point returned an invalid transfer count")
                        if source_id in observations:
                            raise ValueError("Access point returned a duplicate tag identifier")
                        observations[source_id] = TagObservation(source_id, queued)
                        if len(observations) > MAX_TAGS:
                            raise ValueError("Access point tag listing exceeded the tag limit")
                    continuation = payload.get("continu")
                    if continuation is None:
                        return AccessPointSnapshot(tuple(observations.values()))
                    if type(continuation) is not int or not position < continuation <= 255:
                        raise ValueError("Access point returned an invalid continuation")
                    position = continuation
                raise ValueError("Access point tag listing exceeded the page limit")
        except (httpx.HTTPError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await sleep(0.2 * (2**attempt))
    if last_error is None:
        raise RuntimeError("Access point retry loop ended without a result")
    raise last_error


async def fetch_summary(
    host: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AccessPointSnapshot:
    """Compatibility wrapper for the original summary API."""
    return await fetch_snapshot(host, transport=transport)
