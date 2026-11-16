from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import HTTPException

from piphi_network_weatherxm import state
from piphi_network_weatherxm.schemas import DeviceConfig
from piphi_network_weatherxm.weatherxm import WeatherXMError, WeatherXMReading


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClient:
    fail: str | None = None

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def latest_reading(self, station_id: str) -> WeatherXMReading:
        if self.fail:
            raise WeatherXMError(self.fail)
        return WeatherXMReading(
            metrics={"temperature_c": 18.0, "connected": True},
            units={"temperature_c": "C"},
            raw={"address": "private"},
            latest_timestamp="2026-11-16T10:00:00Z",
            latency_ms=3,
            device={"id": station_id, "label": "Roof", "address": "private"},
            observed_at=datetime.now(UTC) - timedelta(minutes=1),
        )

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_config_requires_explicit_station_and_contains_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "WeatherXMClient", FakeClient)
    with pytest.raises(ValueError):
        DeviceConfig(id="wx")

    await state.apply_config(DeviceConfig(
        id="wx", station_id="station-1", api_token="canary-token", username="canary-user", password="canary-password"
    ))
    entry = state.registry.get("wx")

    assert entry is not None
    assert not {"api_token", "username", "password"} & entry["config"].keys()
    assert "canary" not in repr(entry)
    assert "latest_raw" not in entry
    assert "wx" in state._poll_tasks
    await state.remove_config("wx")


@pytest.mark.anyio
async def test_auth_failure_is_redacted_and_marks_last_good_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "WeatherXMClient", FakeClient)
    await state.apply_config(DeviceConfig(id="wx2", station_id="station-2", api_token="token"))
    state._clients["wx2"].fail = "auth"

    snapshot = await state.refresh_entry(state.registry.get("wx2"))

    assert snapshot["temperature_c"] == 18.0
    assert snapshot["connected"] is False
    assert snapshot["stale"] is True
    assert snapshot["error_class"] == "auth"
    await state.remove_config("wx2")


class AuthRejectingClient(FakeClient):
    async def latest_reading(self, station_id: str) -> WeatherXMReading:
        raise WeatherXMError("auth")


@pytest.mark.anyio
async def test_failed_reconfigure_preserves_working_entry_client_and_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "WeatherXMClient", FakeClient)
    await state.apply_config(DeviceConfig(id="rollback", station_id="station-r", api_token="working"))
    old_entry = state.registry.get("rollback")
    old_client = state._clients["rollback"]
    old_task = state._poll_tasks["rollback"]
    monkeypatch.setattr(state, "WeatherXMClient", AuthRejectingClient)

    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="rollback", station_id="station-r", api_token="invalid"))

    assert raised.value.status_code == 401
    assert "update account credentials" in raised.value.detail
    assert state.registry.get("rollback") is old_entry
    assert state._clients["rollback"] is old_client
    assert state._poll_tasks["rollback"] is old_task
    assert not old_task.done()
    await state.remove_config("rollback")


@pytest.mark.anyio
async def test_initial_auth_failure_rejects_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state, "WeatherXMClient", AuthRejectingClient)
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(DeviceConfig(id="rejected", station_id="station-x", api_token="invalid"))
    assert raised.value.status_code == 401
    assert state.registry.get("rejected") is None
    assert "rejected" not in state._clients
    assert "rejected" not in state._poll_tasks


@pytest.mark.anyio
async def test_old_weather_observation_is_stale_and_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class StaleClient(FakeClient):
        async def latest_reading(self, station_id: str) -> WeatherXMReading:
            reading = await super().latest_reading(station_id)
            return WeatherXMReading(
                **{**reading.__dict__, "observed_at": datetime.now(UTC) - timedelta(seconds=state.MAX_SOURCE_AGE_SECONDS + 60)}
            )

    monkeypatch.setattr(state, "WeatherXMClient", StaleClient)
    await state.apply_config(DeviceConfig(id="stale", station_id="station-s", api_token="token"))
    snapshot = state.registry.state_snapshots["stale"]["state"]
    assert snapshot["connected"] is True
    assert snapshot["available"] is False
    assert snapshot["stale"] is True
    assert snapshot["source_age_seconds"] >= state.MAX_SOURCE_AGE_SECONDS
    await state.remove_config("stale")


def test_production_config_rejects_arbitrary_base_url() -> None:
    with pytest.raises(ValueError, match="fixed to the WeatherXM"):
        DeviceConfig(id="ssrf", station_id="station", api_token="token", base_url="http://169.254.169.254/latest")


def test_explicit_test_mode_allows_only_loopback_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ALLOW_TEST_BASE_URL", "1")
    config = DeviceConfig(id="local", station_id="station", api_token="token", base_url="http://localhost:9000/api/v1")
    assert config.base_url == "http://localhost:9000/api/v1"
