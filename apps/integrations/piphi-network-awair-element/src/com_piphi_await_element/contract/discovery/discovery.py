from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import build_discovery_response

from com_piphi_await_element.lib.awair_client import (
    AwairLocalClient,
    AwairTransportError,
    resolve_local_host,
)
from com_piphi_await_element.lib.lifespan import config

discovery_router = APIRouter(tags=["discovery"])
connector = AwairLocalClient.connect


def _identity(service_name: str) -> str | None:
    label = service_name.split(".", 1)[0].strip()
    if not label.upper().startswith("AWAIR-ELEM-"):
        return None
    suffix = label[len("AWAIR-ELEM-") :]
    if not suffix or not all(character.isalnum() or character in "-_" for character in suffix):
        return None
    return label.upper()


async def _devices() -> list[dict]:
    devices: list[dict] = []
    seen: set[str] = set()
    for service_name, item in sorted(config.items()):
        identity = _identity(service_name)
        addresses = item.get("addresses") if isinstance(item, dict) else None
        if identity is None or not isinstance(addresses, list) or not addresses:
            continue
        try:
            address = await resolve_local_host(str(addresses[0]))
            client = await connector(address)
        except AwairTransportError:
            continue
        await client.close()
        if identity in seen:
            continue
        seen.add(identity)
        devices.append(
            {
                "id": identity,
                "device_id": identity,
                "device_identity": identity,
                "device_ip": address,
                "make": "Awair",
                "model": "Element",
                "name": identity,
                "port": 80,
            }
        )
    return devices


@discovery_router.get("/discover")
@discovery_router.get("/discovery")
@discovery_router.post("/discover")
async def get_discovered_devices():
    return build_discovery_response(await _devices())
