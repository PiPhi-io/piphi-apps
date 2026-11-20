from __future__ import annotations

import math

import pytest
from fakes import FakeTapoClient, camera_snapshot
from fastapi import HTTPException
from pydantic import SecretStr

from piphi_network_tapo_cameras.schemas import DeviceConfig
from piphi_network_tapo_cameras.state import (
    apply_config,
    refresh_entry,
    registry,
    remove_config,
    runtime_data,
)
from piphi_network_tapo_cameras.tapo_client import TapoSetupError


def config(password: str = "canary-password") -> DeviceConfig:
    return DeviceConfig(id="front", host="192.0.2.10", username="user@example.invalid", password=SecretStr(password))


@pytest.mark.anyio
async def test_apply_config_publishes_read_only_state_without_secret() -> None:
    client = FakeTapoClient(camera_snapshot(privacy_mode=True))
    runtime_data.connector = lambda **_: _return(client)
    await apply_config(config())
    assert registry.state_snapshots["front"]["state"]["privacy_mode"] is True
    assert registry.state_snapshots["front"]["state"]["camera_enabled"] is False
    assert registry.entries["front"]["hardware_id"] == "opaque-hardware-id"
    assert "canary-password" not in str(registry.entries)


@pytest.mark.anyio
async def test_outage_retains_last_good_values_and_recovers_once() -> None:
    client = FakeTapoClient(
        camera_snapshot(privacy_mode=True),
        TapoSetupError("timeout"),
    )
    runtime_data.connector = lambda **_: _return(client)
    await apply_config(config())
    await refresh_entry(registry.entries["front"])
    state = registry.state_snapshots["front"]["state"]
    assert state["stale"] is True
    assert state["privacy_mode"] is True
    assert [event["event_type"] for event in registry.recent_events].count("device.unavailable") == 1

    recovered = FakeTapoClient(camera_snapshot(privacy_mode=False))
    runtime_data.connector = lambda **_: _return(recovered)
    await refresh_entry(registry.entries["front"])
    assert registry.state_snapshots["front"]["state"]["stale"] is False
    assert [event["event_type"] for event in registry.recent_events].count("device.restored") == 1


@pytest.mark.anyio
async def test_failed_reconfigure_preserves_working_client() -> None:
    working = FakeTapoClient(camera_snapshot())
    runtime_data.connector = lambda **_: _return(working)
    await apply_config(config())

    async def failing(**_):
        raise TapoSetupError("invalid_auth")

    runtime_data.connector = failing
    with pytest.raises(HTTPException):
        await apply_config(config("wrong-password"))
    assert runtime_data.clients["front"] is working
    assert working.closed is False


@pytest.mark.anyio
async def test_failed_candidate_verification_closes_candidate() -> None:
    candidate = FakeTapoClient(TapoSetupError("timeout"))
    runtime_data.connector = lambda **_: _return(candidate)
    with pytest.raises(HTTPException):
        await apply_config(config())
    assert candidate.closed is True
    assert registry.ids() == []


@pytest.mark.anyio
async def test_authentication_failure_stops_automatic_polling() -> None:
    client = FakeTapoClient(camera_snapshot(), TapoSetupError("invalid_auth"))
    runtime_data.connector = lambda **_: _return(client)
    await apply_config(config())
    await refresh_entry(registry.entries["front"])
    assert registry.entries["front"]["availability"] == "reauth_required"
    assert math.isinf(registry.entries["front"]["next_poll_at"])


@pytest.mark.anyio
async def test_masked_secret_only_reuses_same_in_memory_identity() -> None:
    first = FakeTapoClient(camera_snapshot())
    second = FakeTapoClient(camera_snapshot())
    clients = iter([first, second])
    runtime_data.connector = lambda **_: _return(next(clients))
    await apply_config(config())

    await apply_config(config("********"))
    assert runtime_data.configs["front"].password.get_secret_value() == "canary-password"
    assert first.closed is True

    new_config = config("********").model_copy(update={"id": "back", "config_id": "back"})
    with pytest.raises(HTTPException):
        await apply_config(new_config)


@pytest.mark.anyio
async def test_duplicate_hardware_is_rejected_and_deconfigure_closes_transport() -> None:
    first = FakeTapoClient(camera_snapshot())
    duplicate = FakeTapoClient(camera_snapshot())
    clients = iter([first, duplicate])
    runtime_data.connector = lambda **_: _return(next(clients))
    await apply_config(config())
    with pytest.raises(HTTPException):
        await apply_config(config().model_copy(update={"id": "back", "config_id": "back"}))
    assert duplicate.closed is True

    assert await remove_config("front") is True
    assert first.closed is True
    assert registry.ids() == []


async def _return(value):
    return value
