from __future__ import annotations

import httpx
import pytest

from piphi_network_plex.plex_client import PlexClient, PlexServer, normalize_item


PLEX_RESOURCES = """<?xml version="1.0" encoding="UTF-8"?>
<MediaContainer size="3">
  <Device name="Home" clientIdentifier="home-id" provides="server" owned="1" accessToken="home-token">
    <Connection uri="https://relay.example" local="0" relay="1" />
    <Connection uri="http://192.168.1.10:32400" local="1" relay="0" />
  </Device>
  <Device name="Shared" clientIdentifier="shared-id" provides="server" owned="0">
    <Connection uri="https://shared.example:32400" local="0" relay="0" />
  </Device>
  <Device name="Phone" clientIdentifier="phone-id" provides="client">
    <Connection uri="http://phone.invalid" local="1" relay="0" />
  </Device>
</MediaContainer>
"""


@pytest.mark.anyio
async def test_account_discovery_prefers_local_and_uses_device_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/resources"
        assert request.headers["X-Plex-Token"] == "account-token"
        return httpx.Response(200, text=PLEX_RESOURCES)

    client = PlexClient(transport=httpx.MockTransport(handler))
    servers = await client.discover("account-token")

    assert [(server.machine_id, server.base_url) for server in servers] == [
        ("home-id", "http://192.168.1.10:32400"),
        ("shared-id", "https://shared.example:32400"),
    ]
    assert servers[0].token == "home-token"
    assert servers[1].token == "account-token"
    assert servers[1].owned is False


@pytest.mark.anyio
async def test_account_discovery_can_exclude_remote_servers() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, text=PLEX_RESOURCES)
    )
    servers = await PlexClient(transport=transport).discover(
        "account-token",
        include_remote=False,
    )

    assert [server.machine_id for server in servers] == ["home-id"]


@pytest.mark.anyio
async def test_manual_server_discovery_normalizes_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://plex.lan:32400/"
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "machineIdentifier": "manual-id",
                    "friendlyName": "Rack Plex",
                }
            },
        )

    server = (
        await PlexClient(transport=httpx.MockTransport(handler)).discover(
            "secret",
            host="plex.lan",
        )
    )[0]

    assert server == PlexServer(
        "manual-id",
        "Rack Plex",
        "http://plex.lan:32400",
        "secret",
    )


def test_nested_xml_continue_watching_hubs_are_flattened() -> None:
    payload = PlexClient._xml_payload('<MediaContainer><Hub><Video ratingKey="42" title="Film" type="movie"><User title="Owner" /></Video></Hub></MediaContainer>')
    items = PlexClient.metadata(payload)
    assert items[0]["ratingKey"] == "42"
    assert items[0]["User"][0]["title"] == "Owner"


def test_normalize_item_builds_private_provider_artwork_url() -> None:
    item = normalize_item(
        {
            "ratingKey": "42",
            "title": "Example",
            "type": "movie",
            "thumb": "/library/metadata/42/thumb/123",
            "duration": "120000",
            "viewOffset": "45000",
        },
        config_id="account-a",
        server=PlexServer("server-a", "Home", "http://plex", "secret"),
    )

    assert item["id"] == "plex:account-a:server-a:42"
    assert item["duration_seconds"] == 120
    assert item["view_offset_seconds"] == 45
    assert item["artwork_url"].startswith(
        "/provider/account-a%3Aserver-a/asset?path=%2Flibrary%2Fmetadata%2F42"
    )
