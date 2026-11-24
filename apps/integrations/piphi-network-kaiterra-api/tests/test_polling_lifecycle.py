from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from piphi_network_kaiterra_api import state
from piphi_network_kaiterra_api.kaiterra import (
    KaiterraAuthError,
    KaiterraDeviceMetadata,
    KaiterraRateLimitError,
    KaiterraReading,
    normalize_latest_reading,
)
from piphi_network_kaiterra_api.schemas import DeviceConfig

UDID = "46048117-86a7-488e-9c58-708f3470ee11"


class FakeClient:
    fail: Exception | None = None
    observed_age_seconds = 60

    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False

    async def latest_reading(self, _udid: str) -> KaiterraReading:
        if self.fail:
            raise self.fail
        observed = datetime.now(UTC) - timedelta(seconds=self.observed_age_seconds)
        return KaiterraReading(
            metrics={"temperature_c": 21.0, "connected": True},
            units={"temperature_c": "C"},
            latest_timestamp=observed.isoformat(),
            latency_ms=4,
            observed_at=observed,
        )

    async def device_metadata(self, _udid: str) -> KaiterraDeviceMetadata:
        return KaiterraDeviceMetadata(name="Office", model="SE-100", firmware_version="1.2.3")

    async def close(self) -> None:
        self.closed = True


class AuthRejectingClient(FakeClient):
    async def latest_reading(self, _udid: str) -> KaiterraReading:
        raise KaiterraAuthError("authentication")


@pytest.mark.anyio
async def test_config_is_secret_safe_and_removal_cleans_all_runtime_state() -> None:
    state.runtime_data.client_factory = FakeClient
    config = DeviceConfig(id="k1", device_udid=UDID, api_key="canary-super-secret", poll_interval_seconds=60)
    await state.apply_config(config)
    entry = state.registry.get("k1")
    assert entry is not None
    assert "canary-super-secret" not in repr(entry)
    assert UDID not in repr(entry)
    assert "raw" not in repr(entry)
    assert entry["device_ref"] == state.device_ref(UDID)
    assert "k1" in state.runtime_data.poll_tasks
    client = state.runtime_data.clients["k1"]

    assert await state.remove_config("k1") is True
    assert client.closed is True
    assert "k1" not in state.runtime_data.poll_tasks
    assert "k1" not in state.runtime_data.clients
    assert "k1" not in state.runtime_data.configs
    assert "k1" not in state.registry.state_snapshots


@pytest.mark.anyio
async def test_auth_outage_preserves_last_good_values_as_stale() -> None:
    state.runtime_data.client_factory = FakeClient
    await state.apply_config(DeviceConfig(id="k2", device_udid=UDID, api_key="secret"))
    state.runtime_data.clients["k2"].fail = KaiterraAuthError("authentication")
    snapshot = await state.refresh_entry(state.registry.get("k2"))
    assert snapshot["temperature_c"] == 21.0
    assert snapshot["connected"] is False
    assert snapshot["available"] is False
    assert snapshot["stale"] is True
    assert snapshot["error_class"] == "authentication"
    assert snapshot["reauth_required"] is True
    state.runtime_data.clients["k2"].fail = None
    recovered = await state.refresh_entry(state.registry.get("k2"))
    assert recovered["available"] is True
    assert recovered["reauth_required"] is False
    assert len([
        event for event in state.registry.recent_events
        if event["event_type"] == "kaiterra.recovered"
    ]) == 1
    await state.remove_config("k2")


@pytest.mark.anyio
async def test_rate_limit_retry_after_drives_bounded_poll_delay() -> None:
    state.runtime_data.client_factory = FakeClient
    state.runtime_data.jitter = lambda _start, _end: 0.0
    await state.apply_config(DeviceConfig(id="quota", device_udid=UDID, api_key="secret"))
    state.runtime_data.clients["quota"].fail = KaiterraRateLimitError("rate_limit", retry_after_seconds=9000)
    snapshot = await state.refresh_entry(state.registry.get("quota"))
    assert snapshot["error_class"] == "rate_limit"
    assert snapshot["retry_after_seconds"] == 9000
    assert state._poll_delay(state.registry.get("quota")) == 3600
    await state.remove_config("quota")


@pytest.mark.anyio
async def test_old_source_observation_is_explicitly_stale() -> None:
    state.runtime_data.client_factory = FakeClient
    await state.apply_config(DeviceConfig(id="k3", device_udid=UDID, api_key="secret", poll_interval_seconds=60))
    state.runtime_data.clients["k3"].observed_age_seconds = 3600
    snapshot = await state.refresh_entry(state.registry.get("k3"))
    assert snapshot["connected"] is True
    assert snapshot["available"] is False
    assert snapshot["stale"] is True
    assert snapshot["source_age_seconds"] >= 3599
    await state.remove_config("k3")


@pytest.mark.anyio
async def test_state_change_event_has_baseline_and_is_deduplicated() -> None:
    class TransitionClient(FakeClient):
        value = 21.0
        observed = datetime.now(UTC) - timedelta(seconds=60)

        async def latest_reading(self, _udid: str) -> KaiterraReading:
            return KaiterraReading(
                metrics={"temperature_c": self.value, "connected": True},
                units={"temperature_c": "C"},
                latest_timestamp=self.observed.isoformat(),
                latency_ms=1,
                observed_at=self.observed,
            )

    state.runtime_data.client_factory = TransitionClient
    await state.apply_config(DeviceConfig(id="transition", device_udid=UDID, api_key="secret"))
    assert not [event for event in state.registry.recent_events if event["event_type"] == "device.state_changed"]
    await state.refresh_entry(state.registry.get("transition"))
    assert not [event for event in state.registry.recent_events if event["event_type"] == "device.state_changed"]
    client = state.runtime_data.clients["transition"]
    client.value = 22.0
    await state.refresh_entry(state.registry.get("transition"))
    events = [event for event in state.registry.recent_events if event["event_type"] == "device.state_changed"]
    assert len(events) == 1
    assert "temperature_c" in events[0]["payload"]["changed_metrics"]
    await state.remove_config("transition")


@pytest.mark.anyio
async def test_failed_reauth_rolls_back_and_mask_reuses_existing_secret() -> None:
    state.runtime_data.client_factory = FakeClient
    await state.apply_config(DeviceConfig(id="rollback", device_udid=UDID, api_key="working"))
    old_entry = state.registry.get("rollback")
    old_client = state.runtime_data.clients["rollback"]
    old_task = state.runtime_data.poll_tasks["rollback"]
    state.runtime_data.client_factory = AuthRejectingClient
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="rollback", device_udid=UDID, api_key="invalid"))
    assert raised.value.status_code == 401
    assert state.registry.get("rollback") is old_entry
    assert state.runtime_data.clients["rollback"] is old_client
    assert state.runtime_data.poll_tasks["rollback"] is old_task
    assert old_client.closed is False

    state.runtime_data.client_factory = FakeClient
    await state.apply_config(DeviceConfig(id="rollback", device_udid=UDID, api_key="********"))
    assert state.runtime_data.configs["rollback"].api_key.get_secret_value() == "working"
    await state.remove_config("rollback")


@pytest.mark.anyio
async def test_masked_secret_cannot_cross_device_or_configuration() -> None:
    state.runtime_data.client_factory = FakeClient
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="new", device_udid=UDID, api_key="********"))
    assert raised.value.status_code == 422


def test_normalizer_selects_newest_point_and_ignores_motion() -> None:
    metrics, _, timestamp = normalize_latest_reading({"data": [
        {"param": "rtemp", "points": [
            {"ts": "2026-05-10T12:02:00Z", "value": 22.0},
            {"ts": "2026-05-10T12:00:00Z", "value": 20.0},
        ]},
        {"param": "pir", "points": [{"ts": "2026-05-10T12:02:00Z", "value": 1}]},
    ]})
    assert metrics == {"temperature_c": 22.0}
    assert timestamp == "2026-05-10T12:02:00Z"


def test_production_config_rejects_arbitrary_base_url() -> None:
    with pytest.raises(ValueError, match="official Kaiterra"):
        DeviceConfig(id="ssrf", device_udid=UDID, api_key="secret", base_url="http://169.254.169.254/latest")


def test_explicit_test_mode_allows_only_loopback_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_TEST_BASE_URL", "1")
    config = DeviceConfig(id="local", device_udid=UDID, api_key="secret", base_url="http://127.0.0.1:9000/v1")
    assert config.base_url == "http://127.0.0.1:9000/v1"
