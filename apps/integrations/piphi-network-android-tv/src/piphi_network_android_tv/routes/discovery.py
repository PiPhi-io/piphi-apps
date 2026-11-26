from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import IntegrationDiscoveryRequest

from ..adb_sidecar_client import AdbSidecarError
from ..contract import CONFIG_SCHEMA
from ..mdns_discovery import RemoteV2MdnsDiscovery
from ..state import android_tv_service
from ..zeroconf_discovery import ZeroconfDiscoveryBackend

router = APIRouter(tags=["discovery"])
remote_v2_discovery = RemoteV2MdnsDiscovery(ZeroconfDiscoveryBackend())


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    candidates = await remote_v2_discovery.discover()
    adb_candidates = []
    if android_tv_service.adb is not None:
        try:
            adb_candidates = await android_tv_service.adb.discover_pairing_candidates()
        except AdbSidecarError:
            adb_candidates = []
    return {
        "devices": [
            {
                "name": candidate.name,
                "host": candidate.host,
                "port": candidate.port,
                "verification_status": candidate.verification_status,
                "stable_device_id": None,
                "transport": "remote_v2",
            }
            for candidate in candidates
        ]
        + [
            {
                "name": "Android wireless debugging candidate",
                "host": candidate["host"],
                "port": candidate["port"],
                "verification_status": "unverified",
                "stable_device_id": None,
                "transport": "adb",
                "service_type": candidate["service_type"],
            }
            for candidate in adb_candidates
        ]
    }


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
