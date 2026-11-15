from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import IntegrationDiscoveryRequest

from ..contract import CONFIG_SCHEMA
from ..mdns_discovery import RemoteV2MdnsDiscovery
from ..zeroconf_discovery import ZeroconfDiscoveryBackend

router = APIRouter(tags=["discovery"])
remote_v2_discovery = RemoteV2MdnsDiscovery(ZeroconfDiscoveryBackend())


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    candidates = await remote_v2_discovery.discover()
    return {
        "devices": [
            {
                "name": candidate.name,
                "host": candidate.host,
                "port": candidate.port,
                "verification_status": candidate.verification_status,
                "stable_device_id": None,
            }
            for candidate in candidates
        ]
    }


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
