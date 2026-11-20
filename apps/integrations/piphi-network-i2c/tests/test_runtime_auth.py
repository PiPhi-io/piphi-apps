from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from piphi_network_i2c import create_app

OPERATIONAL_ROUTES = (
    ("GET", "/diagnostics"),
    ("POST", "/discover"),
    ("GET", "/entities"),
    ("POST", "/command"),
    ("POST", "/config"),
    ("GET", "/config"),
    ("POST", "/configs/sync"),
    ("POST", "/config/sync"),
    ("POST", "/deconfigure/example"),
    ("POST", "/deconfigure"),
    ("GET", "/events"),
    ("GET", "/manifest.json"),
    ("GET", "/ui-config"),
    ("GET", "/state"),
)


def test_only_health_is_public_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    for method, path in OPERATIONAL_ROUTES:
        response = client.request(method, path)
        assert response.status_code == 503, (method, path, response.text)


def test_runtime_token_is_required_before_route_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "i2c-runtime-token")
    client = TestClient(create_app())

    assert client.get("/entities").status_code == 401
    assert client.get(
        "/entities", headers={"X-PiPhi-Integration-Token": "wrong"}
    ).status_code == 401
    assert client.get(
        "/entities", headers={"X-PiPhi-Integration-Token": "i2c-runtime-token"}
    ).status_code == 200
