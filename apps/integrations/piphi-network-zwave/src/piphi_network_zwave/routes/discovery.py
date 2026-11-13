from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import IntegrationDiscoveryRequest, build_discovery_response

from ..contract import CONFIG_SCHEMA
from .. import state
from ..sidecar_client import SidecarError

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    del payload
    try:
        snapshot = await state.client_factory().snapshot()
    except SidecarError:
        return build_discovery_response([])
    controller = snapshot.get("controller") if isinstance(snapshot.get("controller"), dict) else {}
    return build_discovery_response(
        [
            {
                "id": "primary",
                "device_id": "primary",
                "network_id": "primary",
                "alias": "Home Z-Wave network",
                "controller_ready": controller.get("controllerReady", False),
                "node_count": len(snapshot.get("nodes", [])),
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
