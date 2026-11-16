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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/v1/wyze-bridge/config"),
        ("DELETE", "/v1/wyze-bridge/config"),
        ("GET", "/v1/wyze-bridge/status"),
        ("GET", "/v1/wyze-bridge/cameras"),
    ],
)
async def test_production_control_routes_fail_closed_without_service_token(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.delenv("PIPHI_SIDECAR_TOKEN", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        response = await client.request(method, path, json={} if method == "PUT" else None)

    assert response.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/v1/wyze-bridge/config"),
        ("DELETE", "/v1/wyze-bridge/config"),
        ("GET", "/v1/wyze-bridge/status"),
        ("GET", "/v1/wyze-bridge/cameras"),
    ],
)
async def test_production_control_routes_reject_wrong_service_token(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.setenv("PIPHI_SIDECAR_TOKEN", "correct-token")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        response = await client.request(
            method,
            path,
            headers={"Authorization": "Bearer wrong-token"},
            json={} if method == "PUT" else None,
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_production_control_routes_accept_service_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PIPHI_ENV", "production")
    monkeypatch.setenv("PIPHI_SIDECAR_TOKEN", "correct-token")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://service") as client:
        response = await client.get(
            "/v1/wyze-bridge/status",
            headers={"Authorization": "Bearer correct-token"},
        )

    assert response.status_code == 200
    assert response.json()["state"] == "awaiting_configuration"
