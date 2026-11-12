from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from piphi_network_mikrotik_router import state
from piphi_network_mikrotik_router.routeros import (
    RouterResources,
    _resource_url,
    fetch_resources,
    parse_resources,
)
from piphi_network_mikrotik_router.routes.discovery import discover
from piphi_network_mikrotik_router.routes.entities import entities
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
        return httpx.Response(
            200,
            json=[{"cpu-load": "17", "free-memory": "200", "total-memory": "1000"}],
        )

    result = await fetch_resources(
        "router.example:8443",
        "monitor",
        "private-password",
        transport=httpx.MockTransport(respond),
    )
    assert result == RouterResources(17.0, 80.0)
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/rest/system/resource"
    assert requests[0].url.scheme == "https"
    assert requests[0].headers["authorization"].startswith("Basic ")


@pytest.mark.anyio
async def test_runtime_publishes_resources_without_exposing_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(*_args: object, **_kwargs: object) -> RouterResources:
        return RouterResources(22, 46.5)

    delivered: list[dict] = []
    monkeypatch.setattr(state, "fetch_resources", fake_fetch)
    monkeypatch.setattr(
        state, "schedule_telemetry_delivery", lambda **kwargs: delivered.append(kwargs)
    )
    config = DeviceConfig(
        id="router-widget-test",
        host="router.example",
        username="monitor",
        api_key="private-password",
    )
    entry = state.make_entry(config)
    state.router_passwords[config.id] = str(config.api_key)
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
) -> None:
    async def unavailable(*_args: object, **_kwargs: object) -> RouterResources:
        raise ValueError("vendor response with secret")

    monkeypatch.setattr(state, "fetch_resources", unavailable)
    config = DeviceConfig(
        id="router-error-test", host="router.example", username="monitor"
    )
    entry = state.make_entry(config)
    state.registry.set(config.id, entry)
    try:
        assert (await state.refresh_entry(entry))[
            "reason"
        ] == "missing_router_credentials"
        state.router_passwords[config.id] = "private-password"
        result = await state.refresh_entry(entry)
        assert result == {"connected": False, "reason": "router_resource_fetch_failed"}
        assert "vendor response" not in json.dumps(result)
    finally:
        state.router_passwords.pop(config.id, None)
        state.registry.remove(config.id)


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
