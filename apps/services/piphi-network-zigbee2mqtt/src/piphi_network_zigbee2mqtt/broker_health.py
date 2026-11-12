from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from .bridge_models import MqttCheckResponse


async def check_mqtt_tcp(server: str, *, timeout_seconds: float = 3.0, dry_run: bool = False) -> MqttCheckResponse:
    host, port = parse_mqtt_endpoint(server)
    if dry_run:
        return MqttCheckResponse(ok=True, server=server, host=host, port=port, status="planned")
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_seconds)
        writer.close()
        await writer.wait_closed()
        return MqttCheckResponse(ok=True, server=server, host=host, port=port, status="reachable")
    except Exception as exc:
        return MqttCheckResponse(
            ok=False,
            server=server,
            host=host,
            port=port,
            status="unreachable",
            message=str(exc),
        )


def parse_mqtt_endpoint(server: str) -> tuple[str, int]:
    token = str(server or "").strip()
    if not token:
        raise ValueError("MQTT server is required.")
    parsed = urlparse(token if "://" in token else f"mqtt://{token}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"MQTT server is missing a host: {server}")
    if parsed.port:
        return host, parsed.port
    if parsed.scheme == "mqtts":
        return host, 8883
    if parsed.scheme in {"mqtt", ""}:
        return host, 1883
    raise ValueError(f"Unsupported MQTT scheme: {parsed.scheme}")
