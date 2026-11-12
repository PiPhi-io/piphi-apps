"""Bounded, read-only access-point summary from OpenEPaperLink's tag database."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")


@dataclass(frozen=True)
class AccessPointSummary:
    tag_count: int
    pending_transfer_count: int


def _ap_origin(host: str) -> str:
    raw = host.strip()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("Access point must be a local hostname or IP address")
    parsed = urlsplit(f"http://{raw}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid access-point port") from exc
    if port == 0:
        raise ValueError("Invalid access-point port")
    name = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        if (
            not LOCAL_NAME.fullmatch(name)
            or ".." in name
            or not name.endswith((".local", ".lan"))
        ):
            raise ValueError("Access point must use a local hostname or IP") from None
    else:
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise ValueError("Access point must use a local IP")
    authority = f"[{name}]" if ":" in name else name
    return f"http://{authority}{f':{port}' if port is not None else ''}"


async def fetch_summary(
    host: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AccessPointSummary:
    """Count configured tags and queued transfers without retaining tag identifiers."""
    origin = _ap_origin(host)
    position = 0
    count = 0
    pending = 0
    async with httpx.AsyncClient(timeout=8.0, transport=transport) as client:
        for _ in range(32):
            response = await client.get(f"{origin}/get_db", params={"pos": position})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("tags"), list
            ):
                raise TypeError("Access point returned an invalid tag page")
            tags = payload["tags"]
            for tag in tags:
                if not isinstance(tag, dict):
                    raise TypeError("Access point returned an invalid tag record")
                queued = tag.get("pending", 0)
                if type(queued) is not int or queued < 0:
                    raise ValueError("Access point returned an invalid transfer count")
                count += 1
                pending += queued
            continuation = payload.get("continu")
            if continuation is None:
                return AccessPointSummary(count, pending)
            if type(continuation) is not int or not position < continuation <= 255:
                raise ValueError("Access point returned an invalid continuation")
            position = continuation
    raise ValueError("Access point tag listing exceeded the page limit")
