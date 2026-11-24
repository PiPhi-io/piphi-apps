from __future__ import annotations

import httpx
import pytest

from conftest import RUNTIME_HEADERS
from piphi_network_kaiterra_api.main import app
from piphi_network_kaiterra_api.state import device_ref


@pytest.mark.anyio
async def test_only_health_is_public() -> None:
    transport = httpx.ASGITransport(app=app)
    protected = [
        "/diagnostics", "/discover", "/ui-config", "/contract", "/entities",
        "/state", "/events", "/openapi.json", "/docs",
    ]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        for path in protected:
            assert (await client.get(path)).status_code in {401, 503}, path
        assert (await client.get("/ui-config", headers=RUNTIME_HEADERS)).status_code == 200


@pytest.mark.anyio
async def test_config_rejects_cross_container_payload_scope() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/config",
            headers=RUNTIME_HEADERS,
            json={
                "id": "cross-scope",
                "container_id": "another-container",
                "device_udid": "46048117-86a7-488e-9c58-708f3470ee11",
                "api_key": "not-sent",
            },
        )
    assert response.status_code == 401


@pytest.mark.anyio
async def test_validation_errors_do_not_echo_secret_inputs() -> None:
    canary_key = "canary-api-key-never-echo"
    canary_udid = "canary-udid-never-echo"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/config",
            headers=RUNTIME_HEADERS,
            json={"id": "invalid", "device_udid": canary_udid, "api_key": canary_key},
        )
    assert response.status_code == 422
    assert canary_key not in response.text
    assert canary_udid not in response.text


@pytest.mark.anyio
async def test_discovery_requires_explicit_device_and_returns_only_opaque_identity() -> None:
    udid = "46048117-86a7-488e-9c58-708f3470ee11"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        empty = await client.post("/discover", headers=RUNTIME_HEADERS, json={"inputs": {}})
        selected = await client.post(
            "/discover", headers=RUNTIME_HEADERS,
            json={"inputs": {"device_udid": udid, "alias": "Office"}},
        )
    assert empty.json()["devices"] == []
    record = selected.json()["devices"][0]
    assert record["device_ref"] == device_ref(udid)
    assert udid not in selected.text
