from __future__ import annotations

from fastapi import APIRouter
from piphi_runtime_kit_python import (
    IntegrationDiscoveryRequest,
    build_discovery_response,
    normalize_discovery_inputs,
)

from ..contract import CONFIG_SCHEMA
from ..weatherxm import WeatherXMClient, device_display_name, is_placeholder_secret

router = APIRouter(tags=["discovery"])


@router.post("/discover")
async def discover(payload: IntegrationDiscoveryRequest | None = None):
    inputs = normalize_discovery_inputs(payload.inputs if payload else None)
    api_token = inputs.get("api_token")
    username = inputs.get("username")
    password = inputs.get("password")
    if not is_placeholder_secret(api_token) or (
        not is_placeholder_secret(username) and not is_placeholder_secret(password)
    ):
        client = WeatherXMClient(
            api_token=str(api_token) if api_token else None,
            username=str(username) if username else None,
            password=str(password) if password else None,
            base_url=str(inputs.get("base_url")) if inputs.get("base_url") else None,
        )
        devices = await client.devices()
        return build_discovery_response(
            [
                {
                    "id": str(device.get("id")),
                    "device_id": str(device.get("id")),
                    "station_id": str(device.get("id")),
                    "alias": device_display_name(device, "WeatherXM Station"),
                    "relation": device.get("relation"),
                    "timezone": device.get("timezone"),
                }
                for device in devices
            ]
        )

    station_id = str(inputs.get("station_id") or inputs.get("host") or "weatherxm-station")
    return build_discovery_response(
        [
            {
                "id": station_id,
                "device_id": station_id,
                "station_id": station_id,
                "alias": inputs.get("alias") or "WeatherXM Station",
            }
        ]
    )


@router.get("/ui-config")
async def ui_config():
    return CONFIG_SCHEMA
