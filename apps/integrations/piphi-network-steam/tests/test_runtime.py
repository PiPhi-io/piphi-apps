from __future__ import annotations

import asyncio

from piphi_network_steam.runtime import SteamConfig, _transition_events, registry


def test_config_masks_api_key_and_validates_steamid64() -> None:
    config = SteamConfig(
        id="cfg-1",
        steam_id="76561198000000000",
        web_api_key="top-secret",
    )
    assert "top-secret" not in repr(config)
    assert config.web_api_key.get_secret_value() == "top-secret"


async def test_transition_events_skip_baseline_and_emit_started() -> None:
    registry.recent_events.clear()
    entry = {"config_id": "cfg-1", "steam_id": "76561198000000000"}
    current = {
        "persona_state": "online",
        "current_game_name": "Portal 2",
        "current_game_app_id": "620",
    }
    _transition_events(entry, None, current)
    assert registry.recent_events == []
    _transition_events(entry, {"persona_state": "online", "current_game_name": None}, current)
    await asyncio.sleep(0)
    assert [event["event_type"] for event in registry.recent_events] == ["steam.game.started"]
