from __future__ import annotations

import json

import httpx
import pytest

from piphi_network_passive_ble_monitor.bthome import BTHOME_UUID
from piphi_network_passive_ble_monitor.gateway import GatewayClient, GatewayError, SCHEMA_VERSION


def wire_observation(sequence: int = 1) -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "sequence": sequence,
        "device_handle": "ble_00000000000000000000000000000006",
        "receiver_id": "receiver-1",
        "receiver_kind": "local",
        "observed_monotonic_ms": 1234,
        "ingested_at": "2026-11-15T12:00:00Z",
        "replayed": False,
        "rssi": -60,
        "tx_power": None,
        "connectable": False,
        "address_type": "random",
        "service_uuids": [BTHOME_UUID],
        "manufacturer_data": {},
        "service_data": {BTHOME_UUID: "400161"},
    }


@pytest.mark.anyio
async def test_authenticated_contract_and_narrow_registration_scope() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            assert request.headers["Authorization"] == "Bearer top-secret"
            body = json.loads(request.content)
            assert body["matcher"] == {"device_handles": ["ble_00000000000000000000000000000006"], "service_uuids": [BTHOME_UUID]}
            assert body["scan_mode"] == "passive"
            assert body["queue_capacity"] == 128
            assert body["schema_version"] == "piphi.ble.consumer.v1"
            return httpx.Response(204)
        assert request.headers["Authorization"] == "Bearer top-secret"
        return httpx.Response(200, json={"observations": [wire_observation()], "cursor": 1, "receiver_healthy": True})

    client = GatewayClient("https://gateway.test", "top-secret", transport=httpx.MockTransport(handler))
    try:
        await client.register("consumer one", "ble_00000000000000000000000000000006")
        page = await client.observations("consumer one", after=0, limit=9999)
        assert page.observations[0].service_data[BTHOME_UUID] == bytes.fromhex("400161")
        assert requests[0].url.raw_path.endswith(b"consumer%20one")
        assert requests[1].url.params["limit"] == "256"
    finally:
        await client.close()


@pytest.mark.anyio
async def test_auth_failure_is_actionable_without_echoing_token() -> None:
    client = GatewayClient("https://gateway.test", "do-not-leak", transport=httpx.MockTransport(lambda _request: httpx.Response(401)))
    try:
        with pytest.raises(GatewayError, match="authentication") as caught:
            await client.snapshot("consumer")
        assert "do-not-leak" not in str(caught.value)
    finally:
        await client.close()


@pytest.mark.anyio
async def test_malformed_observation_isolated_with_bounded_hex() -> None:
    malformed = wire_observation(1)
    malformed["service_data"] = {BTHOME_UUID: "zz"}
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"observations": [malformed, wire_observation(2)], "cursor": 2}))
    client = GatewayClient("https://gateway.test", "token", transport=transport)
    try:
        page = await client.observations("consumer", after=0)
        assert [item.sequence for item in page.observations] == [2]
        assert page.malformed_count == 1
    finally:
        await client.close()
