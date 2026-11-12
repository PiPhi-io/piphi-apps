from __future__ import annotations

import httpx
import pytest

from piphi_wyze_camera_service.main import app


@pytest.mark.asyncio
async def test_unconfigured_service_is_healthy_and_has_no_cameras() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        health = await client.get("/health")
        cameras = await client.get("/v1/wyze-bridge/cameras")

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["service"]["state"] == "awaiting_configuration"
    assert cameras.status_code == 503


@pytest.mark.asyncio
async def test_configuration_validation_rejects_empty_secrets() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        response = await client.put(
            "/v1/wyze-bridge/config",
            json={
                "wyze_email": "owner@example.com",
                "wyze_password": "",
                "api_id": "",
                "api_key": "",
            },
        )

    assert response.status_code == 422
