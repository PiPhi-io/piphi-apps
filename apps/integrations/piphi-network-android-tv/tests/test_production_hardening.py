from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_network_android_tv import lifecycle
from piphi_network_android_tv.app import create_app
from piphi_network_android_tv.network_policy import is_allowed_local_address
from piphi_network_android_tv.schemas import DeviceConfig
from piphi_network_android_tv.security import REDACTED, redact


@pytest.mark.anyio
async def test_only_health_is_public_and_wrong_auth_fails_closed() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/diagnostics")).status_code == 401
        response = await client.get(
            "/diagnostics",
            headers={"X-Container-Id": "test-container", "X-PiPhi-Integration-Token": "wrong"},
        )
        assert response.status_code == 401


def test_recursive_redaction_and_local_address_policy() -> None:
    value = {"nested": [{"token": "top-secret", "safe": "ok"}], "pin": "123456"}
    assert redact(value) == {
        "nested": [{"token": REDACTED, "safe": "ok"}],
        "pin": REDACTED,
    }
    assert is_allowed_local_address("192.168.10.4") is True
    assert is_allowed_local_address("169.254.2.3") is True
    assert is_allowed_local_address("127.0.0.1") is False
    assert is_allowed_local_address("8.8.8.8") is False


@pytest.mark.anyio
async def test_startup_rehydrates_core_managed_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_rehydrate_runtime_configs(**kwargs) -> None:
        captured.update(kwargs)

    apply_snapshot = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate_runtime_configs)
    monkeypatch.setattr(lifecycle, "config_sync", SimpleNamespace(apply_snapshot=apply_snapshot))
    await lifecycle.startup_sync(object(), object())
    assert captured["config_model"] is DeviceConfig
    snapshot = RuntimeConfigSnapshot(container_id="test-container", configs=[])
    await captured["apply_snapshot"](snapshot)  # type: ignore[operator]
    assert apply_snapshot.await_args.kwargs["snapshot"] is snapshot
