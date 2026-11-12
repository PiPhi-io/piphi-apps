from __future__ import annotations

import httpx
import pytest

from piphi_network_steam.steam_client import (
    SteamAuthenticationError,
    SteamCredentials,
    SteamWebAPIClient,
    normalize_snapshot,
)


def test_normalize_snapshot_bounds_and_summarizes_visible_activity() -> None:
    snapshot = normalize_snapshot(
        steam_id="76561198000000000",
        player={
            "personaname": "Player\x00",
            "personastate": 1,
            "gameid": "620",
            "gameextrainfo": "Portal 2",
        },
        recent_payload={
            "total_count": 1,
            "games": [{"appid": 620, "name": "Portal 2", "playtime_2weeks": 125}],
        },
        owned_payload={
            "game_count": 2,
            "games": [
                {"appid": 620, "playtime_forever": 500},
                {"appid": 10, "playtime_forever": 25},
            ],
        },
        sampled_at="2026-09-08T00:00:00+00:00",
    )

    assert snapshot.state["persona_name"] == "Player"
    assert snapshot.state["is_online"] is True
    assert snapshot.state["current_game_name"] == "Portal 2"
    assert snapshot.state["recent_playtime_minutes"] == 125
    assert snapshot.state["total_playtime_minutes"] == 525


@pytest.mark.asyncio
async def test_api_key_is_sent_in_header_not_query_string() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if "GetPlayerSummaries" in path:
            payload = {"response": {"players": [{"personaname": "Player", "personastate": 0}]}}
        else:
            payload = {"response": {}}
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = SteamWebAPIClient(http_client=http_client)
        await client.fetch_snapshot(SteamCredentials("76561198000000000", "top-secret"))

    assert len(requests) == 3
    assert all(request.headers["x-webapi-key"] == "top-secret" for request in requests)
    assert all("top-secret" not in str(request.url) for request in requests)


@pytest.mark.asyncio
async def test_summary_auth_error_is_typed() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(403))
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SteamWebAPIClient(http_client=http_client)
        with pytest.raises(SteamAuthenticationError):
            await client.fetch_snapshot(SteamCredentials("76561198000000000", "invalid"))
