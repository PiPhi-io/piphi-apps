from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from piphi_network_openepaperlink import lifecycle, state
from piphi_network_openepaperlink.ap import AccessPointSnapshot, TagObservation
from piphi_network_openepaperlink.main import app
from piphi_network_openepaperlink.privacy import redact
from piphi_network_openepaperlink.schemas import DeviceConfig
from piphi_network_openepaperlink.settings import runtime_port


def snapshot(*ids: str, pending: int = 0) -> AccessPointSnapshot:
    return AccessPointSnapshot(tuple(TagObservation(value, pending) for value in ids))


def test_secret_fields_are_rejected_and_recursive_redaction_is_safe() -> None:
    with pytest.raises(ValidationError):
        DeviceConfig(id="one", host="192.168.1.2", api_key="secret")
    value = {"nested": [{"authorization": "canary"}], "api_key_hint": "canary", "ok": "safe"}
    redacted = redact(value)
    assert "canary" not in json.dumps(redacted)
    assert redacted["ok"] == "safe"


def test_runtime_port_is_bounded_to_a_safe_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "invalid")
    assert runtime_port() == 4219


@pytest.mark.anyio
async def test_only_health_is_public_and_missing_server_auth_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        assert (await client.get("/health")).status_code == 200
        for method, path in (("GET", "/entities"), ("GET", "/diagnostics"), ("POST", "/discover")):
            response = await client.request(method, path)
            assert response.status_code == 503


@pytest.mark.anyio
async def test_configuration_is_connect_before_save_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def online(_host: str) -> AccessPointSnapshot:
        return snapshot("aabbccdd")

    monkeypatch.setattr(state, "snapshot_fetcher", online)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    first = DeviceConfig(id="transaction-test", host="192.168.1.2", alias="old")
    await state.apply_config(first)
    original = dict(state.registry.get("transaction-test") or {})

    async def offline(_host: str) -> AccessPointSnapshot:
        raise httpx.ConnectError("private detail")

    monkeypatch.setattr(state, "snapshot_fetcher", offline)
    with pytest.raises(ConnectionError, match="unavailable"):
        await state.apply_config(
            DeviceConfig(id="transaction-test", host="192.168.1.3", alias="new")
        )
    assert state.registry.get("transaction-test")["alias"] == "old"
    assert state.registry.get("transaction-test")["device_id"] == original["device_id"]
    await state.remove_config("transaction-test")


@pytest.mark.anyio
async def test_last_good_recovery_tag_removal_and_transition_dedupe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results: list[AccessPointSnapshot | Exception] = [
        snapshot("aabbccdd", "11223344", pending=1),
        httpx.ConnectError("offline"),
        httpx.ConnectError("still offline"),
        snapshot("aabbccdd"),
        snapshot("aabbccdd"),
    ]

    async def sequence(_host: str) -> AccessPointSnapshot:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(state, "snapshot_fetcher", sequence)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    await state.apply_config(DeviceConfig(id="lifecycle-test", host="192.168.1.2"))
    entry = state.registry.get("lifecycle-test")
    first_failure = await state.refresh_entry(entry)
    second_failure = await state.refresh_entry(entry)
    recovered = await state.refresh_entry(entry)
    await state.refresh_entry(entry)
    assert first_failure["stale"] is True and first_failure["ap_tag_count"] == 2
    assert second_failure["consecutive_failures"] == 2
    assert recovered["connected"] is True and recovered["ap_tag_count"] == 1
    event_types = [event["event_type"] for event in state.registry.recent_events]
    assert event_types.count("access_point.unavailable") == 1
    assert event_types.count("access_point.recovered") == 1
    assert event_types.count("tag.removed") == 1
    await state.remove_config("lifecycle-test")


@pytest.mark.anyio
async def test_core_restart_rehydrates_even_while_ap_is_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    applied: list[object] = []

    async def fake_rehydrate(**kwargs) -> None:
        applied.append(kwargs["config_model"])

    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    await lifecycle.startup_sync("runtime", "client")
    assert applied == [DeviceConfig]
