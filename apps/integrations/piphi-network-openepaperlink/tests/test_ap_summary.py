from __future__ import annotations

import httpx
import pytest

from piphi_network_openepaperlink.ap import (
    AccessPointSnapshot,
    TagObservation,
    _ap_origin,
    fetch_snapshot,
)


@pytest.mark.anyio
async def test_paginated_inventory_is_pinned_bounded_and_read_only() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params["pos"] == "0":
            return httpx.Response(
                200, json={"tags": [{"mac": "AA:BB:CC:DD", "pending": 2}], "continu": 1}
            )
        return httpx.Response(200, json={"tags": [{"mac": "11:22:33:44", "pending": 1}]})

    snapshot = await fetch_snapshot(
        "openepaperlink.local:8080",
        transport=httpx.MockTransport(respond),
        resolver=lambda _name, _port: _resolved({"192.168.10.25"}),
    )
    assert snapshot.tag_count == 2
    assert snapshot.pending_transfer_count == 3
    assert [request.url.params["pos"] for request in requests] == ["0", "1"]
    assert all(request.method == "GET" and request.url.path == "/get_db" for request in requests)
    assert all(request.url.host == "192.168.10.25" for request in requests)
    assert all(request.headers["host"] == "openepaperlink.local:8080" for request in requests)


async def _resolved(values: set[str]) -> set[str]:
    return values


@pytest.mark.anyio
async def test_ssrf_redirect_dns_rebinding_and_proxy_inputs_fail_closed() -> None:
    for host in (
        "https://example.com",
        "example.com",
        "8.8.8.8",
        "127.0.0.1",
        "169.254.169.254",
        "[fd00:ec2::254]",
        "192.168.1.2/path",
        "user@192.168.1.2",
    ):
        with pytest.raises(ValueError):
            _ap_origin(host)

    with pytest.raises(ValueError, match="outside"):
        await fetch_snapshot(
            "ap.local",
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"tags": []})),
            resolver=lambda _name, _port: _resolved({"192.168.1.2", "1.1.1.1"}),
        )

    with pytest.raises(ValueError, match="redirect"):
        await fetch_snapshot(
            "192.168.1.25",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(302, headers={"location": "http://example.com"})
            ),
            attempts=1,
        )


@pytest.mark.anyio
async def test_retry_schedule_and_malformed_payload_are_deterministic() -> None:
    calls = 0
    delays: list[float] = []

    def flaky(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"tags": [{"mac": "AABBCCDD", "pending": 0}]})

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = await fetch_snapshot("192.168.1.25", transport=httpx.MockTransport(flaky), sleep=sleep)
    assert result == AccessPointSnapshot((TagObservation("aabbccdd", 0),))
    assert calls == 3
    assert delays == [0.2, 0.4]

    with pytest.raises(ValueError, match="stable identifier"):
        await fetch_snapshot(
            "192.168.1.25",
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"tags": [{"pending": 0}]})
            ),
            attempts=1,
        )
