from __future__ import annotations

import httpx
import pytest
from fastapi.routing import APIRoute

from piphi_network_tapo_cameras.main import app


@pytest.mark.anyio
async def test_only_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        for route in app.routes:
            if not isinstance(route, APIRoute) or route.path == "/health":
                continue
            method = next(iter(route.methods - {"HEAD", "OPTIONS"}))
            path = route.path.replace("{config_id}", "fixture")
            response = await client.request(method, path)
            assert response.status_code == 503, (method, route.path, response.text)


@pytest.mark.anyio
async def test_runtime_token_is_constant_time_boundary(monkeypatch) -> None:
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "expected-token")
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/entities")).status_code == 401
        assert (await client.get("/entities", headers={"X-PiPhi-Integration-Token": "wrong"})).status_code == 401
        response = await client.get("/entities", headers={"X-PiPhi-Integration-Token": "expected-token"})
        assert response.status_code == 200
        assert response.json()["entities"] == []
