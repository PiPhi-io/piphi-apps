from __future__ import annotations

import httpx
import pytest

from piphi_network_plex.main import app
from piphi_network_plex.plex_client import PlexServer
from piphi_network_plex.schemas import DeviceConfig
from piphi_network_plex.state import apply_config, plex_service, remove_config


class FakePlexClient:
    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []

    async def discover(self, token: str, **_kwargs):
        prefix = "home" if token == "home-token" else "shared"
        return [
            PlexServer(f"{prefix}-primary", f"{prefix.title()} Primary", "http://plex:32400", token),
            PlexServer(f"{prefix}-backup", f"{prefix.title()} Backup", "http://backup:32400", token),
        ]

    async def request(self, server, path: str, *, params=None, method="GET"):
        self.calls.append((server.machine_id, path, params))
        if path == "/status/sessions" and server.machine_id.endswith("backup"):
            raise httpx.ConnectError("offline")
        if path == "/library/sections":
            return {"MediaContainer": {"Directory": [{"key": "1", "title": "Movies", "type": "movie"}]}}
        return {"MediaContainer": {"Metadata": [{"ratingKey": "42", "title": "Example", "type": "movie", "duration": 120000}]}}

    async def bytes(self, _server, _path):
        return b"image", "image/jpeg"

    @staticmethod
    def media_container(payload):
        return payload.get("MediaContainer", payload)

    @staticmethod
    def metadata(payload):
        container = payload.get("MediaContainer", payload)
        for key in ("Metadata", "Directory"):
            if isinstance(container.get(key), list):
                return container[key]
        return []


@pytest.mark.anyio
async def test_multiple_server_provider_contract():
    original = plex_service.client
    fake = FakePlexClient()
    plex_service.client = fake
    home = DeviceConfig(id="config-1", config_id="config-1", token="home-token")
    shared = DeviceConfig(id="config-2", config_id="config-2", token="shared-token")
    try:
        await apply_config(home)
        await apply_config(shared)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            instances = (await client.get("/provider/instances")).json()
            assert {item["id"] for item in instances["instances"]} == {
                "config-1:home-primary",
                "config-1:home-backup",
                "config-2:shared-primary",
                "config-2:shared-backup",
            }
            scoped = (await client.get("/provider/instances", params={"config_id": "config-1"})).json()
            assert {item["config_id"] for item in scoped["instances"]} == {"config-1"}
            collections = (await client.get("/provider/config-1:home-primary/collections")).json()
            assert collections["collections"][0]["title"] == "Movies"
            items = (await client.get("/provider/config-1:home-primary/items", params={"collection_id": "1"})).json()
            assert items["items"][0]["provider_item_id"] == "42"
            watching = await client.get("/provider/config-1:home-primary/items", params={"hub": "continue_watching", "limit": 8})
            assert watching.status_code == 200
            assert ("home-primary", "/hubs/continueWatching", {"count": 8}) in fake.calls
            action = (await client.post(
                "/provider/config-1:home-primary/actions",
                json={"action": "mark_watched", "item_id": "42"},
            )).json()
            assert action["ok"] is True
            assert ("home-primary", "/:/scrobble", {
                "key": "42",
                "identifier": "com.plexapp.plugins.library",
            }) in fake.calls
    finally:
        await remove_config("config-1")
        await remove_config("config-2")
        plex_service.client = original


@pytest.mark.anyio
async def test_live_widget_bundle_is_served_with_no_unresolved_sdk_import():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/widgets/recently-added/dist/widget.js")
    assert response.status_code == 200
    assert "getInjectedPiPhiWidgetHost" in response.text
    assert 'from "piphi-network-widget-sdk"' not in response.text


@pytest.mark.anyio
async def test_provider_rejects_unknown_actions_and_unsafe_assets():
    original = plex_service.client
    plex_service.client = FakePlexClient()
    config = DeviceConfig(id="config-safe", config_id="config-safe", token="home-token")
    try:
        await apply_config(config)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            unsupported = await client.post(
                "/provider/config-safe:home-primary/actions",
                json={"action": "delete_library", "collection_id": "1"},
            )
            traversal = await client.get(
                "/provider/config-safe:home-primary/asset",
                params={"path": "/library/../Preferences.xml"},
            )

        assert unsupported.status_code == 400
        assert traversal.status_code == 400
    finally:
        await remove_config("config-safe")
        plex_service.client = original
