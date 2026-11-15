from __future__ import annotations

import httpx
import pytest

from piphi_network_bermuda_presence.gateway import BleGatewayClient, CursorGap, GatewayError


@pytest.mark.anyio
async def test_authenticated_gateway_contract_and_bounded_payload() -> None:
    requests: list[httpx.Request] = []

    transport = httpx.MockTransport(lambda request: _response(request, requests))
    client = BleGatewayClient("https://gateway.test", "top-secret", transport=transport)
    await client.register("consumer/a", ["ble_00000000000000000000000000000001"])
    page = await client.observations("consumer/a", after=7, limit=10)
    await client.close()
    assert page.cursor == 8 and page.observations[0].manufacturer_data == {"004c": b"\x00\xff"}
    assert requests[0].headers["authorization"] == "Bearer top-secret"
    assert requests[0].url.raw_path == b"/v1/ble/consumers/consumer%2Fa"
    assert dict(requests[1].url.params) == {"after": "7", "limit": "10"}
    assert "top-secret" not in repr(page)


def _response(request: httpx.Request, requests: list[httpx.Request]) -> httpx.Response:
    requests.append(request)
    if request.method == "PUT":
        return httpx.Response(204)
    return httpx.Response(200, json={"cursor": 8, "observations": [{
        "schema_version": "piphi.ble.observation.v1", "sequence": 8, "device_handle": "ble_00000000000000000000000000000001",
        "receiver_id": "proxy-1", "receiver_kind": "proxy", "observed_monotonic_ms": 100,
        "ingested_at": "2026-01-01T00:00:00Z", "replayed": False, "rssi": -60, "tx_power": -59,
        "connectable": False, "address_type": "random", "service_uuids": [],
        "manufacturer_data": {"004c": "00ff"}, "service_data": {},
    }]})


@pytest.mark.anyio
async def test_cursor_gap_and_secret_redacted_errors() -> None:
    client = BleGatewayClient("https://gateway.test", "secret", transport=httpx.MockTransport(lambda _: httpx.Response(409)))
    with pytest.raises(CursorGap, match="cursor gap"):
        await client.observations("c", after=1)
    await client.close()
    assert "secret" not in str(GatewayError("gateway authentication failed"))
