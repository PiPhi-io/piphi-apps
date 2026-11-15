from __future__ import annotations

import httpx
import pytest

from piphi_ble_gateway_sidecar.ble_models import Advertisement
from piphi_ble_gateway_sidecar.gateway import gateway
from piphi_ble_gateway_sidecar.main import app


@pytest.fixture(autouse=True)
def reset_gateway(tmp_path, monkeypatch):
    gateway.consumers.clear()
    gateway.sequence = 0
    gateway._checkpoint = []
    gateway._dedup = {}
    gateway.secret_path = tmp_path / "key"
    gateway.checkpoint_path = tmp_path / "checkpoint"
    gateway._secret = None


def registration(matcher=None, capacity=4):
    matcher = {"service_uuids": ["180f"]} if matcher is None else matcher
    return {"schema_version": "piphi.ble.consumer.v1", "matcher": matcher,
            "scan_mode": "auto", "queue_capacity": capacity}


@pytest.mark.anyio
async def test_authorization_consumer_isolation_redaction_and_limits() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.put("/v1/ble/consumers/a", json=registration())).status_code == 401
        assert (await client.put("/v1/ble/consumers/a", headers={"Authorization": f"Bearer {'a' * 16}"}, json=registration())).status_code == 200
        assert (await client.put("/v1/ble/consumers/b", headers={"Authorization": f"Bearer {'b' * 16}"}, json=registration())).status_code == 200
        await gateway.ingest(Advertisement("AA:BB:CC:DD:EE:FF", 1000, -60, service_uuids=("180f",)))
        own = await client.get("/v1/ble/observations/a", headers={"Authorization": f"Bearer {'a' * 16}"})
        assert own.status_code == 200 and len(own.json()["observations"]) == 1
        body = own.text
        assert "AA:BB" not in body and "name" not in body.lower()
        denied = await client.get("/v1/ble/observations/b", headers={"Authorization": f"Bearer {'a' * 16}"})
        assert denied.status_code == 403
        for query in ("limit=0", "limit=501", "after=-1", "limit=oops"):
            response = await client.get(f"/v1/ble/observations/a?{query}", headers={"Authorization": f"Bearer {'a' * 16}"})
            assert response.status_code == 422


@pytest.mark.anyio
async def test_catch_all_and_malformed_registration_are_rejected() -> None:
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {'z' * 16}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/v1/ble/consumers/all", headers=headers, json=registration({}))
        assert response.status_code == 422
        assert "bounded matcher" in response.json()["detail"]
        assert (await client.put("/v1/ble/consumers/bad/id", headers=headers, json=registration())).status_code == 404
        assert (await client.put("/v1/ble/consumers/ok", headers=headers, json=registration(capacity=2000))).status_code == 422
        assert (await client.put("/v1/ble/consumers/ok", headers=headers,
                                 json=registration({"service_uuids": ["x" * 65]}))).status_code == 422
        assert (await client.put("/v1/ble/consumers/ok", headers=headers,
                                 json=registration({"device_handles": ["AA:BB:CC:DD:EE:FF"]}))).status_code == 422
