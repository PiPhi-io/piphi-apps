from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from piphi_network_plex import lifecycle
from piphi_network_plex.app import create_app
from piphi_network_plex.plex_client import PlexServer
from piphi_network_plex.schemas import DeviceConfig
from piphi_network_plex.state import apply_config, plex_service, registry


class SequencedClient:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.active = 0
        self.maximum = 0

    async def discover(self, token: str, **_kwargs):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return [PlexServer("server-1", "Home", "http://plex:32400", token)]

    async def request(self, _server, path: str, **_kwargs):
        if path == "/status/sessions":
            return {
                "MediaContainer": {
                    "Metadata": [
                        {
                            "sessionKey": "private-session",
                            "title": "Private title",
                            "User": {"title": "Private user"},
                            "Player": {"title": "Bedroom", "state": "playing"},
                        }
                    ]
                }
            }
        return {"MediaContainer": {"Metadata": []}}

    @staticmethod
    def metadata(payload):
        return payload.get("MediaContainer", {}).get("Metadata", [])


def _path(value: str) -> str:
    return value.replace("{config_id}", "example").replace("{instance_id}", "example")


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


def test_runtime_token_guards_provider_and_widget_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "plex-token")
    client = TestClient(create_app())
    assert client.get("/provider/instances").status_code == 401
    assert client.get("/widgets/plex-server-overview/dist/widget.js").status_code == 401
    headers = {"X-PiPhi-Integration-Token": "plex-token"}
    assert client.get("/provider/instances", headers=headers).status_code == 200
    assert (
        client.get("/widgets/plex-server-overview/dist/widget.js", headers=headers).status_code
        == 200
    )


@pytest.mark.anyio
async def test_transactional_reconfiguration_serialization_and_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = plex_service.client
    fake = SequencedClient(
        [
            True,
            httpx.ConnectError("private upstream failure"),
            httpx.ConnectError("provider down"),
            True,
            True,
            True,
        ]
    )
    plex_service.client = fake
    emitted: list[str] = []
    monkeypatch.setattr(
        "piphi_network_plex.service.schedule_telemetry_delivery", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "piphi_network_plex.service.schedule_event_delivery",
        lambda **kwargs: emitted.append(kwargs["event_type"]),
    )
    config = DeviceConfig(id="private", config_id="private", token="first-secret")
    try:
        await apply_config(config)
        assert isinstance(config.token, SecretStr)
        assert "first-secret" not in repr(config)
        state = registry.state_snapshots["private"]["state"]
        assert state["active_sessions"] == 1
        assert "sessions" not in state

        replacement = config.model_copy(update={"token": SecretStr("replacement-secret")})
        with pytest.raises(httpx.ConnectError):
            await apply_config(replacement)
        retained = plex_service.connections["private"]
        assert retained.config.token.get_secret_value() == "first-secret"

        failed = await plex_service.refresh("private")
        assert failed["available"] is False and failed["stale"] is True
        recovered = await plex_service.refresh("private")
        assert recovered["available"] is True
        assert emitted.count("plex.server.unavailable") == 1
        assert emitted.count("plex.server.recovered") == 1

        results = await asyncio.gather(
            plex_service.refresh("private"), plex_service.refresh("private")
        )
        assert all(result["available"] for result in results)
        assert fake.maximum == 1
    finally:
        plex_service.client = original


@pytest.mark.anyio
async def test_mutations_require_explicit_opt_in() -> None:
    config = DeviceConfig(id="readonly", config_id="readonly", simulation_mode=True)
    await apply_config(config)
    with pytest.raises(Exception, match="disabled"):
        await plex_service.action("readonly:simulated-home", "mark_watched", item_id="movie-1")


@pytest.mark.anyio
async def test_startup_rehydrates_core_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_rehydrate(_starter, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(type(lifecycle.starter), "rehydrate_configs", fake_rehydrate)
    await lifecycle.startup_sync(lifecycle.runtime, "client")
    assert captured["config_model"] is DeviceConfig
    assert captured["apply_snapshot"] is lifecycle.apply_runtime_config_snapshot
