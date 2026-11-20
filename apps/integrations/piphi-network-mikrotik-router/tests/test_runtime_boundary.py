from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_network_mikrotik_router import lifecycle
from piphi_network_mikrotik_router.app import create_app
from piphi_network_mikrotik_router.schemas import DeviceConfig


def _route_path(path: str) -> str:
    return (
        path.replace("{config_id}", "example")
        .replace("{device_id}", "example")
        .replace("{event_type}", "example")
    )


def test_only_health_is_public_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    app = create_app()
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path == "/health":
            continue
        method = next(iter(route.methods - {"HEAD", "OPTIONS"}))
        response = client.request(method, _route_path(route.path))
        assert response.status_code == 503, (method, route.path, response.text)
        assert response.json() == {
            "detail": "runtime authentication is not configured"
        }


def test_runtime_token_is_checked_before_route_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "mikrotik-runtime-token")
    client = TestClient(create_app())

    assert client.get("/contract").status_code == 401
    assert client.get(
        "/contract", headers={"X-PiPhi-Integration-Token": "wrong"}
    ).status_code == 401
    assert client.get(
        "/contract",
        headers={"X-PiPhi-Integration-Token": "mikrotik-runtime-token"},
    ).status_code == 200


@pytest.mark.anyio
async def test_startup_rehydrates_core_managed_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_rehydrate_runtime_configs(**kwargs) -> None:
        captured.update(kwargs)

    apply_snapshot = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(
        lifecycle, "rehydrate_runtime_configs", fake_rehydrate_runtime_configs
    )
    monkeypatch.setattr(
        lifecycle, "config_sync", SimpleNamespace(apply_snapshot=apply_snapshot)
    )

    runtime_context = object()
    client = object()
    await lifecycle.startup_sync(runtime_context, client)

    assert captured["runtime_context"] is runtime_context
    assert captured["client"] is client
    assert captured["config_model"] is DeviceConfig

    snapshot = RuntimeConfigSnapshot(container_id="container-1", configs=[])
    await captured["apply_snapshot"](snapshot)  # type: ignore[operator]
    apply_snapshot.assert_awaited_once()
    call = apply_snapshot.await_args.kwargs
    assert call["snapshot"] is snapshot
    assert call["apply_config"] is lifecycle._apply_rehydrated_config
    assert call["remove_config"] is lifecycle.remove_config
