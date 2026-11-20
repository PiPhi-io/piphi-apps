from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_network_daikin_onecta import lifecycle
from piphi_network_daikin_onecta.schemas import DeviceConfig


@pytest.mark.anyio
async def test_startup_rehydrates_core_managed_oauth_configs(monkeypatch) -> None:
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
    call = apply_snapshot.await_args.kwargs
    assert call["snapshot"] is snapshot
    assert call["apply_config"] is lifecycle._apply_rehydrated_config
    assert call["remove_config"] is lifecycle.remove_config
