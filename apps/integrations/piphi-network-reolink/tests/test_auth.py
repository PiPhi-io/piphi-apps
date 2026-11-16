from __future__ import annotations

import httpx
import pytest

from piphi_network_reolink.main import app


@pytest.mark.anyio
async def test_runtime_routes_fail_closed_without_token(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 503


@pytest.mark.anyio
async def test_runtime_token_is_required(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/entities")).status_code == 401
        response = await client.get(
            "/entities", headers={"X-PiPhi-Integration-Token": "runtime-secret"}
        )
        assert response.status_code == 200
