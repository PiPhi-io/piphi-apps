import json
from pathlib import Path

import httpx
import pytest

from piphi_network_mikrotik_router import state
from piphi_network_mikrotik_router.routeros import RouterOSError, fetch_resources
from piphi_network_mikrotik_router.state import (
    _emit_connectivity_transition,
    _remediation_for,
    _schedule_failure,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.anyio
async def test_automated_permission_denial_matrix() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    for row in contract["denial_matrix"]:
        transport = httpx.MockTransport(
            lambda _request, status=row["status"]: httpx.Response(status)
        )
        with pytest.raises(RouterOSError) as error:
            await fetch_resources(
                "router.test", "monitor", "secret", transport=transport
            )
        assert error.value.reason == row["reason"]
        assert error.value.retryable is row["retryable"]
        assert _remediation_for(error.value.reason) == row["remediation"]


def test_forbidden_permissions_and_mutations_are_not_advertised() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert contract["routeros_group_policies"] == ["read", "rest-api"]
    assert manifest["commands"] == {"refresh": manifest["commands"]["refresh"]}


def test_five_failures_open_a_bounded_circuit() -> None:
    entry = {"config_id": "router-test"}
    for _ in range(5):
        _schedule_failure(entry, retryable=True)
    assert entry["failure_count"] == 5
    assert entry["circuit_open_until"] > 0
    assert entry["next_poll_at"] == entry["circuit_open_until"]


def test_permanent_failure_stops_polling_until_reconfiguration() -> None:
    entry = {"config_id": "router-test"}
    _schedule_failure(entry, retryable=False, reason="authentication_failed")
    assert entry["requires_user_action"] is True
    assert entry["next_poll_at"] == float("inf")
    assert entry["remediation"] == "reauthenticate"


def test_offline_and_recovered_transitions_are_deduplicated(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        state,
        "append_runtime_event",
        lambda event_type, *_args, **_kwargs: events.append(event_type),
    )
    entry = {"latest_metrics": {"connected": True}}
    offline = {"connected": False, "reason": "connection_failed"}
    _emit_connectivity_transition(entry, offline)
    entry["latest_metrics"] = offline
    _emit_connectivity_transition(entry, offline)
    recovered = {"connected": True}
    _emit_connectivity_transition(entry, recovered)
    assert events == ["network.appliance.offline", "network.appliance.recovered"]


@pytest.mark.anyio
async def test_routeros_content_length_is_rejected_before_buffering() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            headers={"content-length": "300000"},
            content=b"{}",
        )
    )
    with pytest.raises(RouterOSError, match="response_size_limit_exceeded"):
        await fetch_resources("router.test", "monitor", "secret", transport=transport)
