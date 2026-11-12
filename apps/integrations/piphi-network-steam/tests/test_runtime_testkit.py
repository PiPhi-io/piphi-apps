from __future__ import annotations

import asyncio

import httpx
import pytest
from piphi_runtime_testkit_python import (
    MockCoreServer,
    assert_entities_response,
    build_config_payload,
    build_runtime_headers,
)

from piphi_network_steam.app import app
from piphi_network_steam.runtime import (
    event_client,
    registry,
    remove_config,
    set_steam_client,
    steam_client,
    telemetry_client,
)
from piphi_network_steam.steam_client import SteamSnapshot


async def wait_for(condition, *, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out waiting for Runtime SDK delivery")


class SequencedSteamClient:
    def __init__(self) -> None:
        self._index = 0

    async def fetch_snapshot(self, _credentials) -> SteamSnapshot:
        games = [None, "Portal 2"]
        game = games[min(self._index, len(games) - 1)]
        self._index += 1
        return SteamSnapshot(
            sampled_at=f"2026-09-08T00:0{self._index}:00+00:00",
            state={
                "steam_id": "76561198000000000",
                "persona_name": "Test Player",
                "profile_url": "https://steamcommunity.com/profiles/76561198000000000",
                "avatar_url": None,
                "community_visibility_state": 3,
                "persona_state": "online",
                "persona_state_code": 1,
                "is_online": True,
                "is_in_game": game is not None,
                "current_game_app_id": "620" if game else None,
                "current_game_name": game,
                "last_logoff": None,
                "library_visible": True,
                "recent_games_visible": True,
                "owned_game_count": 10,
                "recent_game_count": 1,
                "total_playtime_minutes": 500,
                "recent_playtime_minutes": 125,
                "recent_games": [],
            },
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.anyio
async def test_testkit_captures_telemetry_entities_command_and_event() -> None:
    mock_core = MockCoreServer()
    original_client = steam_client
    original_telemetry_url = telemetry_client.core_base_url
    original_event_url = event_client.core_base_url
    set_steam_client(SequencedSteamClient())
    telemetry_client.core_base_url = mock_core.base_url
    event_client.core_base_url = mock_core.base_url
    payload = build_config_payload(
        config_id="steam-test",
        device_id="76561198000000000",
        container_id="steam-container",
        integration_id="piphi-network-steam",
        extra={
            "steam_id": "76561198000000000",
            "web_api_key": "test-only-key",
            "poll_interval_seconds": 3600,
        },
    )
    headers = build_runtime_headers(
        container_id="steam-container",
        internal_token="test-runtime-token",
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            configured = await client.post("/config", json=payload, headers=headers)
            assert configured.status_code == 200, configured.text
            await wait_for(lambda: bool(mock_core.telemetry_requests))
            request = mock_core.assert_telemetry_sent(device_id="76561198000000000")
            assert request.json_body["metrics"]["is_online"] is True

            response = await client.get("/entities")
            entities = assert_entities_response(response.json())["entities"]
            assert entities[0]["device_class"] == "gaming_account"

            refreshed = await client.post(
                "/command",
                headers=headers,
                json={
                    "contract_version": "automation.runtime.command.v1",
                    "command": "refresh",
                    "target": {
                        "config_id": "steam-test",
                        "device_id": "76561198000000000",
                    },
                    "params": {},
                    "capability": "refresh",
                    "capability_requirements": ["refresh"],
                },
            )
            assert refreshed.status_code == 200, refreshed.text
            assert any(
                event["event_type"] == "steam.game.started" for event in registry.recent_events
            ), {"response": refreshed.json(), "events": registry.recent_events}
            await wait_for(
                lambda: any(
                    (request.json_body.get("event_type") or request.json_body.get("type"))
                    == "steam.game.started"
                    for request in mock_core.event_requests
                )
            )
            event = mock_core.assert_event_sent(
                device_id="76561198000000000",
                config_id="steam-test",
                event_type="steam.game.started",
            )
            event_headers = {key.lower(): value for key, value in event.headers.items()}
            assert event_headers["x-container-id"] == "steam-container"
            assert event_headers["x-piphi-integration-token"] == "test-runtime-token"
    finally:
        if registry.get("steam-test") is not None:
            await remove_config("steam-test")
        await asyncio.sleep(0.05)
        telemetry_client.core_base_url = original_telemetry_url
        event_client.core_base_url = original_event_url
        set_steam_client(original_client)
        mock_core.shutdown()
