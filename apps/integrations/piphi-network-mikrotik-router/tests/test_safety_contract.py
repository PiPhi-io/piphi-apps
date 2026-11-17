import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest

from piphi_network_mikrotik_router import routeros, state
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
    endpoints = contract["profiles"]["baseline-monitoring"]
    for endpoint in endpoints:
        for row in contract["denial_matrix"]["every_endpoint"]:
            def handler(request: httpx.Request, *, target=endpoint, denial=row):
                if request.url.path == target["path"]:
                    return httpx.Response(denial["status"])
                if request.url.path.endswith("/license"):
                    return httpx.Response(200, json={"software-id": "opaque-id"})
                return httpx.Response(
                    200,
                    json={
                        "cpu-load": 1,
                        "total-memory": 100,
                        "free-memory": 50,
                        "version": "7.20",
                    },
                )

            with pytest.raises(RouterOSError) as error:
                await fetch_resources(
                    "router.test",
                    "monitor",
                    "secret",
                    transport=httpx.MockTransport(handler),
                )
            assert error.value.reason == row["reason"]
            assert error.value.retryable is row["retryable"]
            assert _remediation_for(error.value.reason) == row["remediation"]


def test_permission_contract_uses_exact_minimum_routeros_policies() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    assert contract["custom_group"]["exact_policies"] == [
        "read",
        "api",
        "rest-api",
    ]
    assert contract["custom_group"]["source_address_required"] is True
    assert contract["actions"] == {}
    assert {
        (endpoint["method"], endpoint["path"])
        for endpoint in contract["profiles"]["baseline-monitoring"]
    } == {
        ("GET", "/rest/system/resource"),
        ("GET", "/rest/system/license"),
    }
    assert "write" in contract["forbidden_policies"]


def test_forbidden_permissions_and_mutations_are_not_advertised() -> None:
    contract = json.loads((ROOT / "permission-contract.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert contract["custom_group"]["exact_policies"] == ["read", "api", "rest-api"]
    assert manifest["commands"] == {"refresh": manifest["commands"]["refresh"]}


def test_five_failures_open_a_bounded_circuit() -> None:
    entry = {"config_id": "router-test"}
    for _ in range(5):
        _schedule_failure(entry, retryable=True)
    assert entry["failure_count"] == 5
    assert entry["circuit_open_until"] > 0
    delay = entry["next_poll_at"] - time.monotonic()
    assert entry["next_poll_at"] >= entry["circuit_open_until"]
    assert 299 <= delay <= 900


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


@pytest.mark.anyio
async def test_routeros_global_and_per_appliance_concurrency_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum = 0
    per_host: dict[str, int] = {}
    per_host_maximum: dict[str, int] = {}
    monkeypatch.setattr(routeros, "_GLOBAL_ENDPOINT_SLOTS", asyncio.Semaphore(3))

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, maximum
        host = request.url.host
        active += 1
        maximum = max(maximum, active)
        per_host[host] = per_host.get(host, 0) + 1
        per_host_maximum[host] = max(per_host_maximum.get(host, 0), per_host[host])
        await asyncio.sleep(0.01)
        per_host[host] -= 1
        active -= 1
        if request.url.path.endswith("/license"):
            return httpx.Response(200, json={"software-id": f"id-{host}"})
        return httpx.Response(
            200,
            json={
                "cpu-load": 1,
                "total-memory": 100,
                "free-memory": 50,
                "version": "7.20",
            },
        )

    await asyncio.gather(
        *(
            fetch_resources(
                f"router-{index}.test",
                "monitor",
                "secret",
                transport=httpx.MockTransport(handler),
            )
            for index in range(6)
        )
    )
    assert maximum == 3
    assert all(
        value <= routeros.MAX_ENDPOINT_CONCURRENCY
        for value in per_host_maximum.values()
    )


@pytest.mark.anyio
async def test_routeros_rate_limit_retry_after_is_honored_and_bounded() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(429, headers={"Retry-After": "1200"})
    )
    with pytest.raises(RouterOSError) as exc_info:
        await fetch_resources("router.test", "monitor", "secret", transport=transport)
    assert exc_info.value.reason == "rate_limited"
    assert exc_info.value.retry_after_seconds == 900

    entry = {"config_id": "router-limited"}
    before = time.monotonic()
    _schedule_failure(
        entry,
        retryable=True,
        reason="rate_limited",
        retry_after_seconds=exc_info.value.retry_after_seconds,
    )
    assert 899 <= entry["next_poll_at"] - before <= 901
