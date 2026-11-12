from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from piphi_network_openepaperlink import state
from piphi_network_openepaperlink.ap import (
    AccessPointSummary,
    _ap_origin,
    fetch_summary,
)
from piphi_network_openepaperlink.routes.discovery import discover
from piphi_network_openepaperlink.routes.entities import entities
from piphi_network_openepaperlink.schemas import DeviceConfig

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.anyio
async def test_paginated_tag_summary_uses_bounded_read_only_endpoint() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params["pos"] == "0":
            return httpx.Response(
                200, json={"tags": [{"mac": "secret", "pending": 2}], "continu": 1}
            )
        return httpx.Response(200, json={"tags": [{"pending": 0}, {"pending": 1}]})

    summary = await fetch_summary(
        "192.168.1.25", transport=httpx.MockTransport(respond)
    )
    assert summary == AccessPointSummary(3, 3)
    assert [request.url.params["pos"] for request in requests] == ["0", "1"]
    assert all(
        request.method == "GET" and request.url.path == "/get_db"
        for request in requests
    )
    assert all(request.url.host == "192.168.1.25" for request in requests)


@pytest.mark.anyio
async def test_invalid_host_and_malformed_pages_fail_closed() -> None:
    for host in ("https://example.com", "example.com", "8.8.8.8", "192.168.1.2/path"):
        with pytest.raises(ValueError):
            _ap_origin(host)
    assert _ap_origin("openepaperlink.local:80") == "http://openepaperlink.local:80"

    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tags": [{}], "continu": 0})

    with pytest.raises(ValueError, match="continuation"):
        await fetch_summary("192.168.1.25", transport=httpx.MockTransport(malformed))


@pytest.mark.anyio
async def test_runtime_emits_real_counts_not_tag_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(_host: str) -> AccessPointSummary:
        return AccessPointSummary(7, 2)

    delivered: list[dict] = []
    monkeypatch.setattr(state, "fetch_summary", fake_fetch)
    monkeypatch.setattr(
        state, "schedule_telemetry_delivery", lambda **kwargs: delivered.append(kwargs)
    )
    config = DeviceConfig(
        id="epaper-widget-test", host="openepaperlink.local", api_key="unused-secret"
    )
    entry = state.make_entry(config)
    state.registry.set(entry["config_id"], entry)
    try:
        result = await state.refresh_entry(entry)
        assert result["ap_tag_count"] == 7
        assert result["ap_pending_transfer_count"] == 2
        assert delivered[0]["metrics"]["ap_tag_count"] == 7
        assert "unused-secret" not in json.dumps(entry)
        assert "mac" not in json.dumps(result)
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_runtime_marks_fetch_failure_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_host: str) -> AccessPointSummary:
        raise ValueError("private upstream detail")

    monkeypatch.setattr(state, "fetch_summary", fail)
    config = DeviceConfig(id="epaper-error-test", host="openepaperlink.local")
    entry = state.make_entry(config)
    state.registry.set(entry["config_id"], entry)
    try:
        result = await state.refresh_entry(entry)
        assert result == {"connected": False, "reason": "ap_fetch_failed"}
        assert "private upstream detail" not in json.dumps(result)
    finally:
        state.registry.remove(entry["config_id"])


@pytest.mark.anyio
async def test_no_synthetic_access_point_when_unconfigured() -> None:
    assert not (await discover()).devices
    assert "demo-device" not in json.dumps(await entities())


def test_widget_binds_only_implemented_ap_summary_capabilities() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    package = json.loads((ROOT / "experiences/ap/package.source.json").read_text())
    assert (
        manifest["ui"]["experience_packages"][0]["registry_id"]
        == "io.piphi.openepaperlink-ap"
    )
    assert package["owning_integration_id"] == manifest["id"]
    (widget,) = package["widgets"]
    assert widget["runtime"] == "declarative"
    assert {slot["capability_requirements"][0] for slot in widget["binding_slots"]} == {
        "ap_tag_count",
        "ap_pending_transfer_count",
    }
