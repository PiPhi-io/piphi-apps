from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot
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
        return snapshot("0011223344556677")

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
        snapshot("0011223344556677", "8899AABBCCDDEEFF", pending=1),
        httpx.ConnectError("offline"),
        httpx.ConnectError("still offline"),
        snapshot("0011223344556677"),
        snapshot("0011223344556677"),
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
    async def online(_host: str) -> AccessPointSnapshot:
        return snapshot("0011223344556677", pending=2)

    monkeypatch.setattr(state, "snapshot_fetcher", online)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = DeviceConfig(id="restart-test", host="192.168.1.2")
    await state.apply_config(config)
    original_tag_ids = list(state.registry.get("restart-test")["tag_ids"])
    persisted_json = Path(os.environ["PIPHI_STATE_SNAPSHOT_PATH"]).read_text()
    assert "0011223344556677" not in persisted_json
    assert original_tag_ids[0] in persisted_json
    state.registry.entries.clear()
    state.registry.state_snapshots.clear()
    state.persisted_state.clear()

    async def offline(_host: str) -> AccessPointSnapshot:
        raise httpx.ConnectError("offline during restart")

    monkeypatch.setattr(state, "snapshot_fetcher", offline)

    async def fake_rehydrate(**kwargs) -> None:
        core_snapshot = RuntimeConfigSnapshot(
            container_id="restart-container", generation=7
        ).model_copy(update={"configs": [config]})
        await kwargs["apply_snapshot"](core_snapshot)

    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    await lifecycle.startup_sync("runtime", "client")
    entry = state.registry.get("restart-test")
    restored = state.registry.state_snapshots["restart-test"]["state"]
    assert entry["tag_ids"] == original_tag_ids
    assert restored["stale"] is True
    assert restored["ap_tag_count"] == 1
    assert restored["ap_pending_transfer_count"] == 2
    assert state.config_sync.get_current_generation() == 7


@pytest.mark.anyio
async def test_config_sync_is_atomic_across_all_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def initial(_host: str) -> AccessPointSnapshot:
        return snapshot("0011223344556677")

    monkeypatch.setattr(state, "snapshot_fetcher", initial)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    await state.apply_config(DeviceConfig(id="old", host="192.168.1.2"))
    state.config_sync.mark_generation(10)
    before = json.dumps(state.registry.entries, sort_keys=True)
    first = DeviceConfig(id="first", host="192.168.1.3")
    second = DeviceConfig(id="second", host="192.168.1.4")
    incoming = RuntimeConfigSnapshot(container_id="sync", generation=11).model_copy(
        update={"configs": [first, second]}
    )

    async def partially_offline(host: str) -> AccessPointSnapshot:
        if host.endswith(".4"):
            raise httpx.ConnectError("second AP unavailable")
        return snapshot("8899AABBCCDDEEFF")

    monkeypatch.setattr(state, "snapshot_fetcher", partially_offline)
    with pytest.raises(ConnectionError, match="unavailable"):
        await state.apply_config_snapshot(incoming)
    assert json.dumps(state.registry.entries, sort_keys=True) == before
    assert state.registry.ids() == ["old"]
    assert state.config_sync.get_current_generation() == 10

    monkeypatch.setattr(state, "snapshot_fetcher", initial)
    response = await state.apply_config_snapshot(incoming)
    assert response.metadata["atomic"] is True
    assert set(state.registry.ids()) == {"first", "second"}
    assert response.removed == ["old"]
    assert state.config_sync.get_current_generation() == 11


@pytest.mark.anyio
async def test_persistence_failure_rolls_back_reconfiguration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def online(_host: str) -> AccessPointSnapshot:
        return snapshot("0011223344556677")

    monkeypatch.setattr(state, "snapshot_fetcher", online)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    await state.apply_config(DeviceConfig(id="persist-rollback", host="192.168.1.2", alias="old"))
    event_count = len(state.registry.recent_events)

    def fail_save(_entries) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(state, "state_saver", fail_save)
    with pytest.raises(OSError, match="disk unavailable"):
        await state.apply_config(
            DeviceConfig(id="persist-rollback", host="192.168.1.2", alias="new")
        )
    assert state.registry.get("persist-rollback")["alias"] == "old"
    assert len(state.registry.recent_events) == event_count


@pytest.mark.anyio
async def test_concurrent_older_snapshot_cannot_overwrite_newer_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newer_started = asyncio.Event()
    release_newer = asyncio.Event()

    async def controlled_fetch(host: str) -> AccessPointSnapshot:
        if host.endswith(".11"):
            newer_started.set()
            await release_newer.wait()
        return snapshot("0011223344556677")

    monkeypatch.setattr(state, "snapshot_fetcher", controlled_fetch)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    newer = RuntimeConfigSnapshot(container_id="sync", generation=11).model_copy(
        update={"configs": [DeviceConfig(id="newer", host="192.168.1.11")]}
    )
    older = RuntimeConfigSnapshot(container_id="sync", generation=10).model_copy(
        update={"configs": [DeviceConfig(id="older", host="192.168.1.10")]}
    )

    newer_task = asyncio.create_task(state.apply_config_snapshot(newer))
    await newer_started.wait()
    older_task = asyncio.create_task(state.apply_config_snapshot(older))
    release_newer.set()
    newer_response, older_response = await asyncio.gather(newer_task, older_task)

    assert newer_response.status == "synced"
    assert older_response.status == "stale_ignored"
    assert state.registry.ids() == ["newer"]
    assert state.config_sync.get_current_generation() == 11


@pytest.mark.anyio
async def test_corrupt_persisted_state_does_not_block_core_rehydration(
    caplog: pytest.LogCaptureFixture,
) -> None:
    Path(os.environ["PIPHI_STATE_SNAPSHOT_PATH"]).write_text("not-json")
    await state.restore_runtime_state()
    assert state.persisted_state == {}
    assert "openepaperlink_state_restore_failed" in caplog.text
