from __future__ import annotations

from uuid import uuid4

import pytest

from solar_edge import state
from solar_edge.solaredge_client import (
    SolarEdgeAuthenticationError,
    SolarEdgeRateLimitError,
)


class FakeService:
    active_config_id = "site-one"

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def refresh(self, *, force_summary: bool):
        assert force_summary is True
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.anyio
async def test_refresh_action_replays_a_success_without_second_api_call(monkeypatch):
    service = FakeService([{"production_power_w": 4200.0}])
    monkeypatch.setattr(state, "solaredge_service", service)
    previous = state.registry.get("site-one")
    state.registry.set(
        "site-one",
        {"config_id": "site-one", "device_id": "solaredge-1234567"},
    )
    key = f"test-success-{uuid4()}"
    request = {
        "command": "refresh",
        "config_id": "site-one",
        "device_id": "solaredge-1234567",
        "idempotency_key": key,
    }

    try:
        first = await state.automations.dispatch(request)
        replay = await state.automations.dispatch(request)
    finally:
        if previous is None:
            state.registry.remove("site-one")
        else:
            state.registry.set("site-one", previous)

    assert first.ok is True
    assert first.result["state"]["production_power_w"] == 4200.0
    assert replay.ok is True
    assert replay.replayed is True
    assert service.calls == 1


@pytest.mark.anyio
async def test_rate_limit_failure_is_retryable_and_not_cached(monkeypatch):
    service = FakeService(
        [SolarEdgeRateLimitError("quota exhausted"), {"connected": True}]
    )
    monkeypatch.setattr(state, "solaredge_service", service)
    key = f"test-retry-{uuid4()}"
    request = {
        "command": "refresh",
        "config_id": "site-one",
        "idempotency_key": key,
    }

    first = await state.automations.dispatch(request)
    second = await state.automations.dispatch(request)

    assert first.ok is False
    assert first.retryable is True
    assert second.ok is True
    assert second.replayed is False
    assert service.calls == 2


@pytest.mark.anyio
async def test_authentication_failure_is_definite_and_replayed(monkeypatch):
    service = FakeService(
        [SolarEdgeAuthenticationError("credentials rejected")]
    )
    monkeypatch.setattr(state, "solaredge_service", service)
    key = f"test-auth-{uuid4()}"
    request = {
        "command": "refresh",
        "config_id": "site-one",
        "idempotency_key": key,
    }

    first = await state.automations.dispatch(request)
    replay = await state.automations.dispatch(request)

    assert first.ok is False
    assert first.retryable is False
    assert replay.replayed is True
    assert service.calls == 1


@pytest.mark.anyio
async def test_refresh_rejects_a_different_config(monkeypatch):
    service = FakeService([{"connected": True}])
    monkeypatch.setattr(state, "solaredge_service", service)

    result = await state.automations.dispatch(
        {"command": "refresh", "config_id": "not-the-active-site"}
    )

    assert result.ok is False
    assert result.retryable is False
    assert service.calls == 0
