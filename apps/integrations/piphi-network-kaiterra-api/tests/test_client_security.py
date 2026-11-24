from __future__ import annotations

import logging

import httpx
import pytest
from pydantic import SecretStr

from fake_transport import ScriptedTransport
from piphi_network_kaiterra_api.kaiterra import (
    KaiterraAuthError,
    KaiterraClient,
    KaiterraContractError,
    KaiterraRateLimitError,
)
from piphi_network_kaiterra_api.security import SecretScrubbingFilter, redact, scrub_url

UDID = "46048117-86a7-488e-9c58-708f3470ee11"
READING = {
    "data": [{
        "param": "rtemp",
        "points": [{"ts": "2026-05-10T12:00:00Z", "value": 21.5}],
    }]
}


@pytest.mark.anyio
async def test_scripted_transport_honors_retry_after_and_provider_quota_headers() -> None:
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    transport = ScriptedTransport([
        httpx.Response(429, headers={"Retry-After": "7"}, json={"error": "limited"}),
        httpx.Response(200, headers={"RateLimit-Remaining": "12"}, json=READING),
    ])
    client = KaiterraClient(
        api_key="canary-query-secret", transport=transport, sleep=sleep,
        jitter=lambda _delay: 0.0,
    )
    reading = await client.latest_reading(UDID)
    await client.close()
    assert delays == [7.0]
    assert reading.rate_limit_remaining == 12
    assert reading.metrics["api_rate_limit_remaining"] == 12
    assert len(transport.requests) == 2


@pytest.mark.anyio
async def test_auth_is_typed_and_never_retried() -> None:
    transport = ScriptedTransport([httpx.Response(401, json={"key": "canary"})])
    client = KaiterraClient(api_key="canary", transport=transport)
    with pytest.raises(KaiterraAuthError):
        await client.latest_reading(UDID)
    assert len(transport.requests) == 1
    await client.close()


@pytest.mark.anyio
async def test_rate_limit_exhaustion_is_typed() -> None:
    transport = ScriptedTransport([
        httpx.Response(429, headers={"Retry-After": "1"}, json={}) for _ in range(3)
    ])

    async def no_sleep(_delay: float) -> None:
        return None

    client = KaiterraClient(api_key="canary", transport=transport, sleep=no_sleep, jitter=lambda _delay: 0.0)
    with pytest.raises(KaiterraRateLimitError) as raised:
        await client.latest_reading(UDID)
    assert raised.value.retry_after_seconds == 1
    await client.close()


@pytest.mark.anyio
async def test_malformed_success_payload_fails_closed() -> None:
    transport = ScriptedTransport([httpx.Response(200, json={"data": "not-a-list"})])
    client = KaiterraClient(api_key="canary", transport=transport)
    with pytest.raises(KaiterraContractError):
        await client.latest_reading(UDID)
    await client.close()


def test_recursive_redaction_and_log_query_scrubbing() -> None:
    canary = "canary-super-secret"
    payload = {
        "nested": [{"api_key": canary}, {"url": f"https://api.kaiterra.com/v1/x?key={canary}&safe=yes"}],
        "secret": SecretStr(canary),
    }
    sanitized = redact(payload)
    assert canary not in repr(sanitized)
    assert sanitized["nested"][0]["api_key"] == "********"
    assert "key=%2A%2A%2A%2A%2A%2A%2A%2A" in sanitized["nested"][1]["url"]
    assert canary not in scrub_url(f"request https://example.test/path?key={canary}")

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "GET https://x.test/a?key=canary-super-secret", (), None)
    SecretScrubbingFilter().filter(record)
    assert canary not in record.getMessage()
