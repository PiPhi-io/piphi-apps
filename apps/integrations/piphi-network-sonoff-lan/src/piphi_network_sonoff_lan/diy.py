"""Read switch state from Sonoff DIY Mode's documented local info endpoint."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import httpx

LOCAL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}\Z")
DEVICE_ID = re.compile(r"[A-Za-z0-9]{4,64}\Z")


def diy_origin(host: str) -> str:
    raw = host.strip()
    if not raw or any(char in raw for char in "/?#@\\"):
        raise ValueError("DIY host must be a local hostname or IP address")
    parsed = urlsplit(f"http://{raw}")
    try:
        port = parsed.port if parsed.port is not None else 8081
    except ValueError as exc:
        raise ValueError("Invalid Sonoff DIY port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Sonoff DIY port")
    name = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        if (
            not LOCAL_NAME.fullmatch(name)
            or ".." in name
            or not name.endswith((".local", ".lan"))
        ):
            raise ValueError("DIY host must be local") from None
    else:
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise ValueError("DIY host must use a local IP")
    authority = f"[{name}]" if ":" in name else name
    return f"http://{authority}:{port}"


async def read_switch_state(
    host: str,
    diy_device_id: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Return a single DIY relay's actual state; reject encrypted/variant replies."""
    if not DEVICE_ID.fullmatch(diy_device_id):
        raise ValueError("Invalid Sonoff DIY device ID")
    origin = diy_origin(host)
    async with httpx.AsyncClient(
        timeout=5.0, transport=transport, follow_redirects=False, trust_env=False
    ) as client:
        response = await client.post(
            f"{origin}/zeroconf/info",
            json={"deviceid": diy_device_id, "data": {}},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get("error") != 0:
        raise ValueError("Sonoff DIY info request was rejected")
    data = payload.get("data")
    switch = data.get("switch") if isinstance(data, dict) else None
    if not isinstance(switch, str) or switch not in {"on", "off"}:
        raise ValueError("Sonoff DIY response has no single switch state")
    return switch == "on"
