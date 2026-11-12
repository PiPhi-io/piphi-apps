from __future__ import annotations

import pytest
import httpx

from piphi_network_plex.main import app
from piphi_network_plex.schemas import DeviceConfig
from piphi_network_plex.simulator import SIMULATED_SERVER, SimulatedPlexClient
from piphi_network_plex.state import apply_config, remove_config


@pytest.mark.asyncio
async def test_simulator_exposes_server_libraries_sessions_and_media() -> None:
    client = SimulatedPlexClient()
    assert (await client.discover("simulator")) == [SIMULATED_SERVER]
    libraries = client.metadata(await client.request(SIMULATED_SERVER, "/library/sections"))
    assert [item["title"] for item in libraries] == ["Movies", "TV Shows", "Music"]
    sessions = client.metadata(await client.request(SIMULATED_SERVER, "/status/sessions"))
    assert sessions[0]["Player"]["state"] == "playing"
    results = client.metadata(await client.request(SIMULATED_SERVER, "/hubs/search", params={"query": "orbit"}))
    assert [item["ratingKey"] for item in results] == ["episode-1"]
    artwork, content_type = await client.bytes(SIMULATED_SERVER, "/simulator/art/quiet-orbit.svg")
    assert content_type == "image/svg+xml"
    assert b"Quiet Orbit" in artwork


@pytest.mark.anyio
async def test_simulation_mode_drives_real_provider_routes() -> None:
    config = DeviceConfig(
        id="plex-simulator",
        config_id="plex-simulator",
        simulation_mode=True,
    )
    try:
        await apply_config(config)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            instances = (await client.get("/provider/instances")).json()["instances"]
            instance_id = instances[0]["id"]
            collections = (await client.get(f"/provider/{instance_id}/collections")).json()
            watching = (await client.get(
                f"/provider/{instance_id}/items",
                params={"hub": "continue_watching"},
            )).json()
            searched = (await client.get(
                f"/provider/{instance_id}/items",
                params={"q": "orbit"},
            )).json()
            resolved = (await client.post(
                f"/provider/{instance_id}/resolve",
                json={"item_id": "episode-1"},
            )).json()
            artwork = await client.get(
                f"/provider/{instance_id}/asset",
                params={"path": "/simulator/art/quiet-orbit.svg"},
            )
            watched = (await client.post(
                f"/provider/{instance_id}/actions",
                json={"action": "mark_watched", "item_id": "episode-1"},
            )).json()

        assert collections["total"] == 3
        assert watching["items"][0]["provider"] == "plex"
        assert searched["items"][0]["provider_item_id"] == "episode-1"
        assert resolved["item"]["title"] == "A Quiet Orbit"
        assert artwork.status_code == 200
        assert artwork.headers["content-type"].startswith("image/svg+xml")
        assert b"Quiet Orbit" in artwork.content
        assert watched["ok"] is True
    finally:
        await remove_config("plex-simulator")
