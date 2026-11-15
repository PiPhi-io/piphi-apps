from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from piphi_network_bermuda_presence import state
from piphi_network_bermuda_presence.gateway import GatewayError
from piphi_network_bermuda_presence.schemas import DeviceConfig
from piphi_network_bermuda_presence.state import make_entry


def valid_config() -> dict[str, object]:
    return {
        "id": "home-presence",
        "gateway_url": "https://gateway.local",
        "api_token": "super-secret",
        "consumer_id": "presence-home",
        "selected_device_handles": ["ble_00000000000000000000000000000001"],
        "receivers": [{"receiver_id": "proxy-1", "area_id": "kitchen", "area_name": "Kitchen"}],
    }


def test_config_rejects_partial_auth_duplicates_and_unsafe_transport() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        DeviceConfig.model_validate({"id": "x", "gateway_url": "https://gateway.local", "selected_device_handles": ["x"]})
    duplicate = valid_config() | {"selected_device_handles": ["same", "same"]}
    with pytest.raises(ValidationError, match="unique"):
        DeviceConfig.model_validate(duplicate)
    insecure = valid_config() | {"gateway_url": "http://gateway.local"}
    with pytest.raises(ValidationError, match="HTTPS"):
        DeviceConfig.model_validate(insecure)


def test_runtime_entry_never_contains_gateway_token() -> None:
    entry = make_entry(DeviceConfig.model_validate(valid_config()))
    serialized = json.dumps(entry, default=str)
    assert "super-secret" not in serialized
    assert "api_token" not in entry["config"]


@pytest.mark.anyio
async def test_configuration_is_transactional_when_gateway_validation_fails(monkeypatch) -> None:
    config = DeviceConfig.model_validate(valid_config())
    stopped = False

    class RejectingCoordinator:
        gateway_available = False

        def __init__(self, *_args, **_kwargs):
            pass

        async def start(self) -> None:
            raise GatewayError("gateway unavailable")

        async def stop(self) -> None:
            nonlocal stopped
            stopped = True

    state.registry.remove(config.id)
    state.coordinators.pop(config.id, None)
    monkeypatch.setattr(state, "PresenceCoordinator", RejectingCoordinator)

    with pytest.raises(GatewayError, match="gateway unavailable"):
        await state.apply_config(config)

    assert stopped is True
    assert state.registry.get(config.id) is None
    assert config.id not in state.coordinators


@pytest.mark.anyio
async def test_different_config_id_cannot_duplicate_gateway_device(monkeypatch) -> None:
    existing = DeviceConfig.model_validate(valid_config())
    duplicate = DeviceConfig.model_validate(
        valid_config() | {"id": "duplicate-presence", "consumer_id": "another-consumer"}
    )
    state.registry.set(existing.id, make_entry(existing))
    monkeypatch.setattr(
        state,
        "PresenceCoordinator",
        lambda *_args, **_kwargs: pytest.fail("duplicate must be rejected before gateway registration"),
    )
    try:
        with pytest.raises(HTTPException) as caught:
            await state.apply_config(duplicate)
        assert caught.value.status_code == 409
        assert existing.id in str(caught.value.detail)
    finally:
        state.registry.remove(existing.id)


@pytest.mark.anyio
async def test_same_id_update_does_not_unregister_replacement_consumer(monkeypatch) -> None:
    config = DeviceConfig.model_validate(valid_config())
    stopped_with: list[bool] = []

    class ConnectedCoordinator:
        gateway_available = True

        def __init__(self, current: DeviceConfig, *_args, **_kwargs):
            self.config = current
            self.consumer_id = current.consumer_id

        async def start(self) -> None:
            pass

        async def stop(self, *, unregister: bool = True) -> None:
            stopped_with.append(unregister)

        def entity_states(self) -> dict[str, object]:
            return {}

    old = ConnectedCoordinator(config)
    state.coordinators[config.id] = old
    state.registry.set(config.id, make_entry(config))
    monkeypatch.setattr(state, "PresenceCoordinator", ConnectedCoordinator)
    try:
        await state.apply_config(config)
        assert stopped_with == [False]
    finally:
        state.coordinators.pop(config.id, None)
        state.registry.remove(config.id)
