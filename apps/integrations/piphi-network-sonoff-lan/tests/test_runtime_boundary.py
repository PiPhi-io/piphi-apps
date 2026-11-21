from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_network_sonoff_lan import lifecycle
from piphi_network_sonoff_lan.app import create_app
from piphi_network_sonoff_lan.schemas import DeviceConfig


def _path(value: str) -> str:
    return value.replace("{config_id}", "example").replace("{device_id}", "example")


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
        assert client.request(method, _path(route.path)).status_code == 503
    assert client.get("/openapi.json").status_code == 503


def test_runtime_token_guards_operational_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "sonoff-token")
    client = TestClient(create_app())
    assert client.get("/contract").status_code == 401
    assert (
        client.get("/contract", headers={"X-PiPhi-Integration-Token": "wrong"}).status_code == 401
    )
    assert (
        client.get("/contract", headers={"X-PiPhi-Integration-Token": "sonoff-token"}).status_code
        == 200
    )


@pytest.mark.anyio
async def test_startup_rehydrates_core_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    async def fake_rehydrate(**kwargs):
        captured.update(kwargs)

    apply_snapshot = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    monkeypatch.setattr(lifecycle, "config_sync", SimpleNamespace(apply_snapshot=apply_snapshot))
    await lifecycle.startup_sync("runtime", "client")
    assert captured["config_model"] is DeviceConfig
    snapshot = RuntimeConfigSnapshot(container_id="container", configs=[])
    await captured["apply_snapshot"](snapshot)
    assert apply_snapshot.await_args.kwargs["apply_config"] is lifecycle._apply_rehydrated_config
