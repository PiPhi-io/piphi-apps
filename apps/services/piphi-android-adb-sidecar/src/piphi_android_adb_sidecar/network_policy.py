from __future__ import annotations

import asyncio
import ipaddress
import socket


def is_allowed_local_address(value: str) -> bool:
    address = ipaddress.ip_address(value.split("%", 1)[0])
    return bool(
        (address.is_private or address.is_link_local)
        and not address.is_loopback
        and not address.is_multicast
        and not address.is_unspecified
    )


async def require_local_endpoint(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("endpoint hostname could not be resolved") from exc
        addresses = tuple(sorted({str(record[4][0]) for record in records}))
    else:
        addresses = (str(literal),)
    if not addresses or any(not is_allowed_local_address(item) for item in addresses):
        raise ValueError("endpoint must resolve exclusively to private or link-local addresses")
    return addresses
