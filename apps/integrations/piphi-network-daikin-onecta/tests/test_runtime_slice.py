from __future__ import annotations

from typing import Any, ClassVar

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from test_normalization import provider_payload

from piphi_network_daikin_onecta import state
from piphi_network_daikin_onecta.main import app
from piphi_network_daikin_onecta.onecta import AccountSnapshot, OnectaError, Quota
from piphi_network_daikin_onecta.schemas import DeviceConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClient:
    instances: ClassVar[list[FakeClient]] = []
    failure: str | None = None
    closed = False
    patches: list[dict[str, Any]]

    def __init__(self, token: str) -> None:
        self.token = token
        self.patches = []
        self.__class__.instances.append(self)

    async def fetch_devices(self) -> AccountSnapshot:
        if self.failure:
            raise OnectaError(self.failure)
        return AccountSnapshot(
            provider_payload(), Quota(minute_remaining=8, day_remaining=99)
        )

    async def set_target_temperature(self, **kwargs: Any) -> Quota:
        self.patches.append(kwargs)
        return Quota(minute_remaining=7, day_remaining=98)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
async def clean_runtime(monkeypatch: pytest.MonkeyPatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(state.runtime_data, "client_factory", FakeClient)
    yield
    for config_id in list(state.registry.ids()):
        await state.remove_config(config_id)


@pytest.mark.anyio
async def test_account_poll_creates_dynamic_entities_without_storing_token() -> None:
    await state.apply_config(
        DeviceConfig(
            id="account-1",
            oauth_subject="subject-private",
            access_token="canary-secret",
        )
    )
    entry = state.registry.get("account-1")
    assert entry is not None
    assert len(entry["climate_points"]) == 1
    assert "access_token" not in entry["config"]
    assert "canary-secret" not in repr(entry)
    assert "subject-private" not in repr(entry)
    assert "gateway-private-id" not in repr(entry)
    assert "climateControl" not in repr(entry)
    snapshot = state.registry.state_snapshots["account-1"]["state"]
    assert snapshot["climate_count"] == 1
    assert snapshot["devices"][0]["indoor_temperature_c"] == 20.5


@pytest.mark.anyio
async def test_failure_preserves_last_good_state_as_stale_and_recovery_clears_it() -> (
    None
):
    await state.apply_config(
        DeviceConfig(id="account-2", oauth_subject="s2", access_token="secret")
    )
    entry = state.registry.get("account-2")
    client = state.runtime_data.clients["account-2"]
    client.failure = "provider_unavailable"
    stale = await state.refresh_entry(entry)
    assert stale["stale"] is True
    assert stale["devices"][0]["indoor_temperature_c"] == 20.5
    assert stale["devices"][0]["stale"] is True
    client.failure = None
    recovered = await state.refresh_entry(entry)
    assert recovered["stale"] is False
    assert entry["consecutive_failures"] == 0


@pytest.mark.anyio
async def test_target_control_requires_opt_in_and_validates_range_and_step() -> None:
    await state.apply_config(
        DeviceConfig(id="disabled", oauth_subject="d", access_token="secret")
    )
    disabled_entry = state.registry.get("disabled")
    device_id = disabled_entry["climate_points"][0]["device_id"]
    with pytest.raises(HTTPException, match="climate_control_disabled"):
        await state.set_target_temperature("disabled", device_id, 21.5)

    await state.apply_config(
        DeviceConfig(
            id="enabled",
            oauth_subject="e",
            access_token="secret",
            enable_climate_control=True,
        )
    )
    entry = state.registry.get("enabled")
    target = entry["climate_points"][0]["device_id"]
    with pytest.raises(HTTPException, match="target_temperature_out_of_range"):
        await state.set_target_temperature("enabled", target, 31.0)
    with pytest.raises(HTTPException, match="target_temperature_off_step"):
        await state.set_target_temperature("enabled", target, 21.2)

    result = await state.set_target_temperature("enabled", target, 21.5)
    assert result["target_temperature_c"] == 21.5
    assert state.runtime_data.clients["enabled"].patches == [
        {
            "gateway_id": "gateway-private-id",
            "management_point_id": "climateControl",
            "path": "/operationModes/heating/setpoints/roomTemperature",
            "value": 21.5,
        }
    ]


@pytest.mark.anyio
async def test_failed_reconfigure_preserves_working_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await state.apply_config(
        DeviceConfig(id="rollback", oauth_subject="same", access_token="working")
    )
    old_entry = state.registry.get("rollback")
    old_client = state.runtime_data.clients["rollback"]

    class RejectingClient(FakeClient):
        async def fetch_devices(self) -> AccountSnapshot:
            raise OnectaError("invalid_auth")

    monkeypatch.setattr(state.runtime_data, "client_factory", RejectingClient)
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(
            DeviceConfig(id="rollback", oauth_subject="same", access_token="bad")
        )
    assert raised.value.status_code == 401
    assert state.registry.get("rollback") is old_entry
    assert state.runtime_data.clients["rollback"] is old_client
    assert old_client.closed is False


@pytest.mark.anyio
async def test_masked_token_only_reuses_same_in_memory_account() -> None:
    await state.apply_config(
        DeviceConfig(id="masked", oauth_subject="same", access_token="working")
    )
    await state.apply_config(
        DeviceConfig(id="masked", oauth_subject="same", access_token="********")
    )
    assert (
        state.runtime_data.configs["masked"].access_token.get_secret_value()
        == "working"
    )

    with pytest.raises(HTTPException, match="access_token_required"):
        await state.apply_config(
            DeviceConfig(id="other", oauth_subject="other", access_token="********")
        )


@pytest.mark.anyio
async def test_auth_failure_stops_polling_until_core_refreshes_token() -> None:
    await state.apply_config(
        DeviceConfig(id="reauth", oauth_subject="r", access_token=SecretStr("token"))
    )
    entry = state.registry.get("reauth")
    state.runtime_data.clients["reauth"].failure = "invalid_auth"

    await state.refresh_entry(entry)

    assert entry["availability"] == "reauth_required"
    assert entry["next_poll_at"] == float("inf")


@pytest.mark.anyio
async def test_quota_and_failure_backoff_never_poll_faster_than_configured() -> None:
    entry = {
        "poll_interval_seconds": 300,
        "consecutive_failures": 2,
        "quota": {"retry_after_seconds": None, "minute_remaining": 0},
    }
    assert state._next_delay(entry) == 1200
    entry["quota"]["retry_after_seconds"] = 1800
    assert state._next_delay(entry) == 1800


@pytest.mark.anyio
async def test_temperature_command_is_idempotent_and_never_fans_out() -> None:
    await state.apply_config(
        DeviceConfig(
            id="command",
            oauth_subject="command-subject",
            access_token="secret",
            enable_climate_control=True,
        )
    )
    entry = state.registry.get("command")
    device_id = entry["climate_points"][0]["device_id"]
    payload = {
        "command": "set_target_temperature",
        "target": {"config_id": "command", "device_id": device_id},
        "params": {"target_temperature_c": 22.0},
    }
    headers = {"X-PiPhi-Idempotency-Key": "onecta-temperature-command-1"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/command", json=payload, headers=headers)
        replay = await client.post("/command", json=payload, headers=headers)
        fanout = await client.post(
            "/command",
            json={
                "command": "set_target_temperature",
                "target": {"config_id": "command"},
                "params": {"target_temperature_c": 22.5},
            },
        )

    assert first.status_code == 200
    assert first.json()["status"] == "success"
    assert replay.json()["replayed"] is True
    assert len(state.runtime_data.clients["command"].patches) == 1
    assert fanout.json()["status"] == "failed"
    assert len(state.runtime_data.clients["command"].patches) == 1
