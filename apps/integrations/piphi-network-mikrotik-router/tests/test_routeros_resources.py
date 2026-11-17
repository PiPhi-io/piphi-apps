from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_mikrotik_router import state
from piphi_network_mikrotik_router.routeros import (
    RouterOSError,
    RouterResources,
    _resource_url,
    fetch_resources,
    parse_resources,
)
from piphi_network_mikrotik_router.routes.discovery import discover
from piphi_network_mikrotik_router.routes.entities import entities
from piphi_network_mikrotik_router.routes.health import diagnostics
from piphi_network_mikrotik_router.schemas import DeviceConfig

ROOT = Path(__file__).resolve().parents[1]


def test_resource_parser_normalizes_routeros_string_numbers() -> None:
    reading = parse_resources(
        [{"cpu-load": "24", "free-memory": "768", "total-memory": "1024"}]
    )
    assert reading == RouterResources(24.0, 25.0)
    for invalid in (
        {"cpu-load": "nan", "free-memory": "5", "total-memory": "10"},
        {"cpu-load": "101", "free-memory": "5", "total-memory": "10"},
        {"cpu-load": "10", "free-memory": "11", "total-memory": "10"},
    ):
        with pytest.raises(ValueError):
            parse_resources(invalid)


def test_router_url_rejects_paths_credentials_and_invalid_ports() -> None:
    assert _resource_url("192.168.88.1:8443") == (
        "https://192.168.88.1:8443/rest/system/resource"
    )
    for invalid in (
        "http://router",
        "router/rest/system",
        "admin@router",
        "router:bad",
    ):
        with pytest.raises(ValueError):
            _resource_url(invalid)


@pytest.mark.anyio
async def test_fetch_uses_authenticated_https_read_only_endpoint() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/rest/system/license":
            return httpx.Response(200, json={"software-id": "ABCD-1234"})
        return httpx.Response(
            200,
            json=[
                {
                    "cpu-load": "17",
                    "free-memory": "200",
                    "total-memory": "1000",
                    "version": "7.20",
                }
            ],
        )

    result = await fetch_resources(
        "router.example:8443",
        "monitor",
        "private-password",
        transport=httpx.MockTransport(respond),
    )
    assert result == RouterResources(17.0, 80.0, "ABCD-1234", "7.20")
    assert {request.url.path for request in requests} == {
        "/rest/system/resource",
        "/rest/system/license",
    }
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.scheme == "https" for request in requests)
    assert all(
        request.headers["authorization"].startswith("Basic ") for request in requests
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "reason", "retryable"),
    [
        (401, "authentication_failed", False),
        (403, "permission_denied", False),
        (404, "routeros_rest_unsupported", False),
        (429, "rate_limited", True),
        (503, "routeros_server_error", True),
    ],
)
async def test_fetch_classifies_safe_failures(
    status: int, reason: str, retryable: bool
) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status, text="password=must-not-leak")
    )
    with pytest.raises(RouterOSError) as exc_info:
        await fetch_resources(
            "router.example", "monitor", "private-password", transport=transport
        )
    assert exc_info.value.reason == reason
    assert exc_info.value.retryable is retryable
    assert "must-not-leak" not in str(exc_info.value)


@pytest.mark.anyio
async def test_runtime_publishes_resources_without_exposing_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*_args: object, **_kwargs: object) -> RouterResources:
        return RouterResources(22, 46.5, "ABCD-1234", "7.20")

    delivered: list[dict] = []
    monkeypatch.setattr(state, "fetch_resources", fake_fetch)
    monkeypatch.setattr(
        state, "schedule_telemetry_delivery", lambda **kwargs: delivered.append(kwargs)
    )
    config = DeviceConfig(
        id="router-widget-test",
        host="router.example",
        username="monitor",
        password="private-password",
    )
    entry = state.make_entry(config)
    state.router_passwords[config.id] = config.secret_password()
    state.registry.set(config.id, entry)
    try:
        result = await state.refresh_entry(entry)
        assert result["cpu_load_percent"] == 22
        assert result["memory_used_percent"] == 46.5
        assert delivered[0]["metrics"]["cpu_load_percent"] == 22
        assert "private-password" not in json.dumps(entry)
        assert "private-password" not in json.dumps(result)
    finally:
        state.router_passwords.pop(config.id, None)
        state.registry.remove(config.id)


@pytest.mark.anyio
async def test_runtime_fails_closed_without_credentials_or_on_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> RouterResources:
        raise ValueError("vendor response with secret")

    monkeypatch.setattr(state, "fetch_resources", unavailable)
    config = DeviceConfig(
        id="router-error-test",
        host="router.example",
        username="monitor",
        password="private-password",
    )
    entry = state.make_entry(config)
    state.registry.set(config.id, entry)
    try:
        missing_credentials = await state.refresh_entry(entry)
        assert missing_credentials["reason"] == "missing_router_credentials"
        assert missing_credentials["last_attempt_at"]
        state.router_passwords[config.id] = "private-password"
        result = await state.refresh_entry(entry)
        assert result["connected"] is False
        assert result["reason"] == "missing_router_credentials"
        assert result["last_attempt_at"] == missing_credentials["last_attempt_at"]
        assert result["requires_user_action"] is True
        assert entry["next_poll_at"] == float("inf")
        entry["requires_user_action"] = False
        entry.pop("permanent_failure", None)
        result = await state.refresh_entry(entry)
        assert result["reason"] == "router_resource_fetch_failed"
        assert result["last_attempt_at"]
        assert result["stale"] is False
        assert "vendor response" not in json.dumps(result)
        assert config.id not in caplog.text
        assert config.host not in caplog.text
    finally:
        state.router_passwords.pop(config.id, None)
        state.registry.remove(config.id)


@pytest.mark.anyio
async def test_reconfigure_rejects_identity_change_transactionally(monkeypatch) -> None:
    config_id = "stable-router"
    existing = {
        "config_id": config_id,
        "device_id": state._opaque_device_id("ORIGINAL-ID"),
        "host": "old-router.example",
        "config": {"host": "old-router.example", "username": "monitor"},
    }

    async def different_router(*_args, **_kwargs):
        return RouterResources(10, 20, "DIFFERENT-ID", "7.20")

    monkeypatch.setattr(state, "fetch_resources", different_router)
    state.registry.set(config_id, existing)
    state.router_passwords[config_id] = "working-password"
    try:
        replacement = DeviceConfig(
            id=config_id,
            host="new-router.example",
            username="monitor",
            password="new-password",
        )
        with pytest.raises(ValueError, match="different RouterOS appliance"):
            await state.apply_config(replacement)
        assert state.registry.get(config_id) is existing
        assert state.router_passwords[config_id] == "working-password"
    finally:
        state.router_passwords.pop(config_id, None)
        state.registry.remove(config_id)


def test_widget_tracks_router_resource_capabilities() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    package = json.loads((ROOT / "experiences/health/package.source.json").read_text())
    assert manifest["ui"]["experience_packages"][0]["registry_id"] == (
        "io.piphi.mikrotik-health"
    )
    assert package["owning_integration_id"] == manifest["id"]
    (widget,) = package["widgets"]
    assert widget["runtime"] == "declarative"
    assert {slot["capability_requirements"][0] for slot in widget["binding_slots"]} == {
        "cpu_load_percent",
        "memory_used_percent",
    }


@pytest.mark.anyio
async def test_unconfigured_router_does_not_advertise_demo_device() -> None:
    discovery = await discover()
    runtime_entities = await entities()
    assert not discovery.devices
    assert "demo-device" not in json.dumps(runtime_entities)


def test_legacy_api_key_migrates_without_serialization() -> None:
    config = DeviceConfig(
        id="legacy", host="router.example", username="monitor", api_key="secret"
    )
    assert config.secret_password() == "secret"
    assert "secret" not in json.dumps(config.model_dump(), default=str)


def test_custom_ca_is_confined_to_approved_mounts() -> None:
    for path in (
        "/tmp/router-ca.pem",
        "/run/secrets-evil/router-ca.pem",
        "/run/secrets/../outside/router-ca.pem",
        "run/secrets/router-ca.pem",
    ):
        with pytest.raises(ValueError, match="approved read-only"):
            DeviceConfig(
                id="ca",
                host="router.example",
                username="monitor",
                password="secret",
                ca_bundle_path=path,
            )


@pytest.mark.anyio
async def test_diagnostics_omit_raw_config_and_host_identifiers() -> None:
    config_id = "sensitive-config-name"
    entry = {
        "config_id": config_id,
        "device_id": state._opaque_device_id("SOFTWARE-ID"),
        "host": "private-router.example",
        "latest_metrics": {"connected": False, "stale": True},
    }
    state.registry.set(config_id, entry)
    try:
        payload = json.dumps(await diagnostics(), default=str)
        assert config_id not in payload
        assert entry["host"] not in payload
        assert entry["device_id"] not in payload
    finally:
        state.registry.remove(config_id)
