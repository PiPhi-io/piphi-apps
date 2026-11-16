from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from piphi_network_kaiterra_api import state
from piphi_network_kaiterra_api.kaiterra import KaiterraError, KaiterraReading, normalize_latest_reading
from piphi_network_kaiterra_api.schemas import DeviceConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClient:
    fail: str | None = None
    closed = False
    observed_age_seconds = 60

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def latest_reading(self, _udid: str) -> KaiterraReading:
        if self.fail:
            raise KaiterraError(self.fail)
        observed = datetime.now(UTC) - timedelta(seconds=self.observed_age_seconds)
        return KaiterraReading(
            metrics={"temperature_c": 21.0, "connected": True},
            units={"temperature_c": "C"},
            raw={"secret-shaped": "payload"},
            latest_timestamp=observed.isoformat(),
            latency_ms=4,
            observed_at=observed,
        )

    async def device_metadata(self, _udid: str) -> dict[str, Any]:
        return {"name": "Office", "address": "private"}

    async def close(self) -> None:
        self.closed = True


class AuthRejectingClient(FakeClient):
    async def latest_reading(self, _udid: str) -> KaiterraReading:
        raise KaiterraError("auth")


@pytest.mark.anyio
async def test_config_owns_client_poll_task_and_contains_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "KaiterraClient", FakeClient)
    config = DeviceConfig(id="k1", device_udid="udid-1", api_key="canary-super-secret", poll_interval_seconds=60)

    await state.apply_config(config)
    entry = state.registry.get("k1")

    assert entry is not None
    assert "api_key" not in entry["config"]
    assert "canary-super-secret" not in repr(entry)
    assert "latest_raw" not in entry
    assert "device_metadata" not in entry
    assert "k1" in state._poll_tasks
    await state.remove_config("k1")
    assert "k1" not in state._poll_tasks
    assert "k1" not in state._clients


@pytest.mark.anyio
async def test_outage_preserves_last_good_values_as_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "KaiterraClient", FakeClient)
    await state.apply_config(DeviceConfig(id="k2", device_udid="udid-2", api_key="secret"))
    client = state._clients["k2"]
    client.fail = "auth"

    snapshot = await state.refresh_entry(state.registry.get("k2"))

    assert snapshot["temperature_c"] == 21.0
    assert snapshot["connected"] is False
    assert snapshot["available"] is False
    assert snapshot["stale"] is True
    assert snapshot["error_class"] == "auth"
    await state.remove_config("k2")


@pytest.mark.anyio
async def test_old_source_observation_is_explicitly_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "KaiterraClient", FakeClient)
    await state.apply_config(DeviceConfig(id="k3", device_udid="udid-3", api_key="secret", poll_interval_seconds=60))
    state._clients["k3"].observed_age_seconds = 3600

    snapshot = await state.refresh_entry(state.registry.get("k3"))

    assert snapshot["connected"] is True
    assert snapshot["available"] is False
    assert snapshot["stale"] is True
    assert snapshot["source_age_seconds"] >= 3599
    await state.remove_config("k3")


def test_normalizer_selects_newest_point_not_last_array_item() -> None:
    metrics, _, timestamp = normalize_latest_reading({"data": [{
        "param": "rtemp",
        "units": "unexpected",
        "points": [
            {"ts": "2026-05-10T12:02:00Z", "value": 22.0},
            {"ts": "2026-05-10T12:00:00Z", "value": 20.0},
        ],
    }]})
    assert metrics["temperature_c"] == 22.0
    assert timestamp == "2026-05-10T12:02:00Z"


@pytest.mark.anyio
async def test_failed_reconfigure_preserves_working_entry_client_and_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "KaiterraClient", FakeClient)
    await state.apply_config(DeviceConfig(id="rollback", device_udid="udid-r", api_key="working"))
    old_entry = state.registry.get("rollback")
    old_client = state._clients["rollback"]
    old_task = state._poll_tasks["rollback"]
    monkeypatch.setattr(state, "KaiterraClient", AuthRejectingClient)

    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="rollback", device_udid="udid-r", api_key="invalid"))

    assert raised.value.status_code == 401
    assert "update the API key" in raised.value.detail
    assert state.registry.get("rollback") is old_entry
    assert state._clients["rollback"] is old_client
    assert state._poll_tasks["rollback"] is old_task
    assert not old_task.done()
    assert old_client.closed is False
    await state.remove_config("rollback")


@pytest.mark.anyio
async def test_initial_auth_failure_rejects_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "KaiterraClient", AuthRejectingClient)
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="rejected", device_udid="udid-x", api_key="invalid"))
    assert raised.value.status_code == 401
    assert state.registry.get("rejected") is None
    assert "rejected" not in state._clients
    assert "rejected" not in state._poll_tasks


def test_production_config_rejects_arbitrary_base_url() -> None:
    with pytest.raises(ValueError, match="official Kaiterra"):
        DeviceConfig(id="ssrf", device_udid="udid", api_key="secret", base_url="http://169.254.169.254/latest")


def test_explicit_test_mode_allows_only_loopback_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_TEST_BASE_URL", "1")
    config = DeviceConfig(id="local", device_udid="udid", api_key="secret", base_url="http://127.0.0.1:9000/v1")
    assert config.base_url == "http://127.0.0.1:9000/v1"
