from __future__ import annotations

import httpx
import pytest

from piphi_network_steam.steam_client import (
    SteamAuthenticationError,
    SteamCredentials,
    SteamRateLimitError,
    SteamResponseError,
    SteamWebAPIClient,
    _retry_after_seconds,
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


@pytest.mark.asyncio
async def test_rate_limit_preserves_bounded_retry_after() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"Retry-After": "240"})
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SteamWebAPIClient(http_client=http_client)
        with pytest.raises(SteamRateLimitError) as captured:
            await client.fetch_snapshot(SteamCredentials("76561198000000000", "limited"))
    assert captured.value.retry_after_seconds == 240


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500), "HTTP 500"),
        (httpx.Response(200, text="not-json"), "invalid JSON"),
        (httpx.Response(200, json=[]), "unexpected payload"),
    ],
)
@pytest.mark.asyncio
async def test_provider_failures_are_sanitized(response: httpx.Response, message: str) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SteamWebAPIClient(http_client=http_client)
        with pytest.raises(SteamResponseError, match=message):
            await client._get("/test", SteamCredentials("76561198000000000", "secret"))


@pytest.mark.asyncio
async def test_network_failure_is_typed_and_owned_client_closes() -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret must not appear", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http_client:
        client = SteamWebAPIClient(http_client=http_client)
        with pytest.raises(SteamResponseError, match="ConnectError") as captured:
            await client._get("/test", SteamCredentials("76561198000000000", "secret"))
        assert "secret must not appear" not in str(captured.value)
    owned = SteamWebAPIClient()
    await owned._client()
    await owned.aclose()


def test_retry_after_parser_is_bounded_and_fail_closed() -> None:
    assert _retry_after_seconds(None) == 60
    assert _retry_after_seconds("1") == 60
    assert _retry_after_seconds("99999") == 3600
    assert _retry_after_seconds("invalid") == 60
