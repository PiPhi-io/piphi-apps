from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from piphi_network_steam import lifespan, runtime
from piphi_network_steam.app import create_app
from piphi_network_steam.steam_client import (
    SteamAuthenticationError,
    SteamRateLimitError,
    SteamSnapshot,
)


def _snapshot(*, game: str | None = None, minute: int = 1) -> SteamSnapshot:
    return SteamSnapshot(
        sampled_at=f"2026-11-21T17:{minute:02d}:00+00:00",
        state={
            "steam_id": "76561198000000000",
            "persona_name": "Private Player",
            "profile_url": "https://steamcommunity.com/private",
            "avatar_url": "https://cdn.example/private.png",
            "last_logoff": 123456,
            "recent_games": [{"name": "Private history"}],
            "persona_state": "online",
            "persona_state_code": 1,
            "is_online": True,
            "is_in_game": game is not None,
            "current_game_app_id": "620" if game else None,
            "current_game_name": game,
            "library_visible": True,
            "recent_games_visible": True,
            "owned_game_count": 2,
            "recent_game_count": 1,
            "total_playtime_minutes": 500,
            "recent_playtime_minutes": 25,
        },
    )


class FakeClient:
    def __init__(self, outcomes) -> None:
        self.outcomes = iter(outcomes)
        self.active = 0
        self.maximum = 0

    async def fetch_snapshot(self, _credentials) -> SteamSnapshot:
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self) -> None:
        return None


def _path(value: str) -> str:
    return value.replace("{config_id}", "example").replace("{device_id}", "example")


def test_only_health_is_public_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    app = create_app()
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path == "/health":
            continue
        method = next(iter(route.methods - {"HEAD", "OPTIONS"}))
        assert client.request(method, _path(route.path)).status_code == 503
    assert client.get("/openapi.json").status_code == 503


def test_runtime_token_guards_operational_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "steam-token")
    client = TestClient(create_app())
    assert client.get("/entities").status_code == 401
    assert (
        client.get("/entities", headers={"X-PiPhi-Integration-Token": "wrong"}).status_code == 401
    )
    assert (
        client.get("/entities", headers={"X-PiPhi-Integration-Token": "steam-token"}).status_code
        == 200
    )


@pytest.mark.anyio
async def test_startup_rehydrates_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_rehydrate(_starter, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(type(runtime.starter), "rehydrate_configs", fake_rehydrate)
    await lifespan.startup_sync(runtime.runtime, "client")
    assert captured["config_model"] is runtime.SteamConfig
    assert captured["apply_snapshot"] is runtime.apply_runtime_config_snapshot


@pytest.mark.anyio
async def test_secret_storage_transactional_reconfigure_and_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runtime.steam_client
    fake = FakeClient([_snapshot(), SteamAuthenticationError("rejected")])
    runtime.set_steam_client(fake)
    monkeypatch.setattr(runtime, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = runtime.SteamConfig(
        id="steam-private",
        steam_id="76561198000000000",
        web_api_key="first-secret",
        poll_interval_seconds=3600,
    )
    try:
        entry = await runtime.apply_config(config)
        assert isinstance(entry["web_api_key"], SecretStr)
        assert "first-secret" not in repr(entry)
        state = runtime.registry.state_snapshots["steam-private"]["state"]
        assert not ({"profile_url", "avatar_url", "last_logoff", "recent_games"} & state.keys())
        duplicate = config.model_copy(update={"id": "duplicate-account"})
        with pytest.raises(Exception, match="already configured"):
            await runtime.apply_config(duplicate)
        replacement = config.model_copy(update={"web_api_key": SecretStr("bad-secret")})
        with pytest.raises(Exception, match="rejected"):
            await runtime.apply_config(replacement)
        retained = runtime.registry.get("steam-private")
        assert retained is entry
        assert retained["web_api_key"].get_secret_value() == "first-secret"
        runtime._record_failure("steam-private", SteamAuthenticationError("rejected"))
        failed = runtime.registry.state_snapshots["steam-private"]["state"]
        assert failed["reauth_required"] is True
        assert failed["failure_reason"] == "authentication_required"
    finally:
        await runtime.remove_config("steam-private")
        runtime.set_steam_client(original)


@pytest.mark.anyio
async def test_serialized_refresh_stale_backoff_and_transition_deduplication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runtime.steam_client
    fake = FakeClient(
        [
            _snapshot(minute=1),
            SteamRateLimitError("limited", retry_after_seconds=240),
            SteamRateLimitError("limited", retry_after_seconds=240),
            _snapshot(game="Portal 2", minute=5),
        ]
    )
    runtime.set_steam_client(fake)
    monkeypatch.setattr(runtime, "schedule_telemetry_delivery", lambda **_kwargs: None)
    monkeypatch.setattr(runtime, "schedule_event_delivery", lambda **_kwargs: None)
    offset = len(runtime.registry.recent_events)
    try:
        await runtime.apply_config(
            runtime.SteamConfig(
                id="steam-recovery",
                steam_id="76561198000000000",
                web_api_key="secret",
                poll_interval_seconds=3600,
            )
        )
        results = await asyncio.gather(
            runtime._read_and_store("steam-recovery"),
            runtime._read_and_store("steam-recovery"),
            return_exceptions=True,
        )
        assert all(isinstance(item, SteamRateLimitError) for item in results)
        failed = runtime.registry.state_snapshots["steam-recovery"]["state"]
        assert failed["available"] is False and failed["stale"] is True
        assert runtime.poll_status["steam-recovery"]["retry_after_seconds"] == 240
        await runtime._read_and_store("steam-recovery")
        assert fake.maximum == 1
        events = [e["event_type"] for e in runtime.registry.recent_events[offset:]]
        assert events.count("steam.account.unavailable") == 1
        assert events.count("steam.account.recovered") == 1
    finally:
        await runtime.remove_config("steam-recovery")
        runtime.set_steam_client(original)


def test_diagnostics_exclude_state_and_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")
    response = TestClient(create_app()).get("/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert "state_snapshots" not in body.get("diagnostics", {})
    assert "web_api_key" not in response.text


@pytest.mark.anyio
async def test_authenticated_runtime_routes_cover_account_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = runtime.steam_client
    runtime.set_steam_client(FakeClient([_snapshot(), _snapshot(), _snapshot(game="Portal 2")]))
    monkeypatch.setattr(runtime, "schedule_telemetry_delivery", lambda **_kwargs: None)
    monkeypatch.setattr(runtime, "schedule_event_delivery", lambda **_kwargs: None)
    headers = {"X-PiPhi-Integration-Token": "route-token"}
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "route-token")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver"
        ) as client:
            discovered = await client.post(
                "/discover",
                headers=headers,
                json={
                    "inputs": {
                        "steam_id": "76561198000000000",
                        "web_api_key": "secret",
                    }
                },
            )
            assert discovered.status_code == 200
            configured = await client.post(
                "/config",
                headers=headers,
                json={
                    "id": "route-account",
                    "steam_id": "76561198000000000",
                    "web_api_key": "secret",
                    "poll_interval_seconds": 3600,
                },
            )
            assert configured.status_code == 200
            assert (await client.get("/ui-config", headers=headers)).status_code == 200
            assert (await client.get("/diagnostics", headers=headers)).status_code == 200
            assert (await client.get("/entities", headers=headers)).json()["entities"]
            assert (await client.get("/state", headers=headers)).status_code == 200
            assert (await client.get("/events", headers=headers)).status_code == 200
            unsupported = await client.post(
                "/command",
                headers=headers,
                json={"command": "launch", "config_id": "route-account"},
            )
            assert unsupported.status_code == 400
            refreshed = await client.post(
                "/command",
                headers=headers,
                json={
                    "command": "refresh",
                    "entity_id": "account:route-account",
                    "params": {},
                },
            )
            assert refreshed.status_code == 200
            missing = await client.post("/deconfigure", headers=headers, json={"config": {}})
            assert missing.status_code == 400
            removed = await client.post(
                "/deconfigure",
                headers=headers,
                json={"config": {"config_id": "route-account"}},
            )
            assert removed.status_code == 200
    finally:
        if runtime.registry.get("route-account") is not None:
            await runtime.remove_config("route-account")
        runtime.set_steam_client(original)
