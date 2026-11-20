from __future__ import annotations

import json

import httpx
import pytest

from piphi_network_daikin_onecta.onecta import OnectaClient, OnectaError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_fetches_account_once_and_parses_quota() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[{"id": "gateway-1", "managementPoints": []}],
            headers={
                "X-RateLimit-Remaining-Minute": "7",
                "X-RateLimit-Remaining-Day": "42",
            },
        )

    client = OnectaClient(
        "secret-token",
        transport=httpx.MockTransport(handler),
        base_url="https://test.invalid",
    )
    snapshot = await client.fetch_devices()
    await client.close()

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/gateway-devices"
    assert requests[0].headers["Authorization"] == "Bearer secret-token"
    assert snapshot.devices[0]["id"] == "gateway-1"
    assert snapshot.quota.minute_remaining == 7
    assert snapshot.quota.day_remaining == 42


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "invalid_auth"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
    ],
)
async def test_maps_provider_failures(status: int, category: str) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(status, headers={"Retry-After": "90"})
    )
    client = OnectaClient(
        "secret", transport=transport, base_url="https://test.invalid"
    )
    with pytest.raises(OnectaError) as raised:
        await client.fetch_devices()
    await client.close()
    assert raised.value.category == category
    assert raised.value.retry_after_seconds == 90


@pytest.mark.anyio
async def test_temperature_patch_is_single_bounded_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, headers={"X-RateLimit-Remaining-Minute": "5"})

    client = OnectaClient(
        "secret",
        transport=httpx.MockTransport(handler),
        base_url="https://test.invalid",
    )
    quota = await client.set_target_temperature(
        gateway_id="gateway/1",
        management_point_id="climate Control",
        path="/operationModes/heating/setpoints/roomTemperature",
        value=21.5,
    )
    await client.close()

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PATCH"
    assert request.url.raw_path == (
        b"/v1/gateway-devices/gateway%2F1/management-points/climate%20Control/"
        b"characteristics/temperatureControl"
    )
    assert json.loads(request.content) == {
        "path": "/operationModes/heating/setpoints/roomTemperature",
        "value": 21.5,
    }
    assert quota.minute_remaining == 5
