from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_modbus_rtu_sidecar import lifecycle, state
from piphi_modbus_rtu_sidecar.main import app
from piphi_modbus_rtu_sidecar.profile import profile_hash
from piphi_modbus_rtu_sidecar.schemas import DeviceConfig


@pytest.mark.anyio
async def test_shutdown_closes_every_bus_when_one_session_close_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    scripted_session_factory,
    sidecar_config: Callable[..., DeviceConfig],
) -> None:
    """One broken adapter must not strand unrelated serial buses on shutdown."""
    monkeypatch.setattr(state, "session_factory", scripted_session_factory)
    config_ids = ("failing-close", "healthy-close")
    for config_id in config_ids:
        await state.apply_config(sidecar_config(config_id))

    active = [state.get_controller(config_id) for config_id in config_ids]
    first, second = scripted_session_factory.sessions
    first.close_error = OSError("private adapter detail")
    try:
        await state.shutdown_controllers()
        assert first.close_calls == 1
        assert second.close_calls == 1
        assert all(controller.port_open is False for controller in active)
        assert state.controllers == {}
        assert "error=OSError" in caplog.text
        assert "private adapter detail" not in caplog.text
    finally:
        first.close_error = None
        for config_id in config_ids:
            await state.remove_config(config_id)


@pytest.mark.anyio
async def test_reconfigure_opens_candidate_before_releasing_working_session(
    monkeypatch: pytest.MonkeyPatch,
    scripted_session_factory,
    sidecar_config: Callable[..., DeviceConfig],
) -> None:
    """A replacement is proven before the working adapter is released."""
    monkeypatch.setattr(state, "session_factory", scripted_session_factory)
    config_id = "replacement-order"
    try:
        await state.apply_config(sidecar_config(config_id, baud_rate=9600))
        original = state.get_controller(config_id)
        await state.apply_config(sidecar_config(config_id, baud_rate=19200))
        replacement = state.get_controller(config_id)

        assert replacement is not original
        assert scripted_session_factory.events == [
            ("open", config_id),
            ("open", config_id),
            ("close", config_id),
        ]
        assert scripted_session_factory.sessions[0].opened is False
        assert scripted_session_factory.sessions[1].opened is True
    finally:
        await state.remove_config(config_id)


@pytest.mark.anyio
async def test_startup_rehydrates_authoritative_core_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restart restoration uses the same apply/remove lifecycle as live config."""
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
    snapshot = RuntimeConfigSnapshot(container_id="sidecar-container", configs=[])
    await captured["apply_snapshot"](snapshot)  # type: ignore[operator]

    assert captured["runtime_context"] is runtime_context
    assert captured["client"] is client
    assert captured["config_model"] is DeviceConfig
    call = apply_snapshot.await_args.kwargs
    assert call["snapshot"] is snapshot
    assert call["apply_config"] is state.apply_config
    assert call["remove_config"] is state.remove_config
    assert call["get_active_config_ids"]() == state.registry.ids()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("error", "error_code", "counter"),
    [
        (
            TimeoutError("modbus_response_timeout"),
            "modbus_response_timeout",
            "timeout_count",
        ),
        (ValueError("invalid_modbus_crc"), "invalid_modbus_crc", "crc_error_count"),
        (ValueError("invalid_modbus_lrc"), "invalid_modbus_lrc", "lrc_error_count"),
        (
            ValueError("private /dev/serial detail"),
            "ValueError",
            "transport_error_count",
        ),
    ],
    ids=("timeout", "crc", "lrc", "unsafe-error-detail"),
)
async def test_refresh_failure_matrix_retains_last_good_value_and_safe_error(
    monkeypatch: pytest.MonkeyPatch,
    scripted_session_factory,
    sidecar_config: Callable[..., DeviceConfig],
    error: BaseException,
    error_code: str,
    counter: str,
) -> None:
    """Read failures retain last-good data while quality and metrics degrade."""
    monkeypatch.setattr(state, "session_factory", scripted_session_factory)
    config_id = f"failure-{counter}"
    try:
        await state.apply_config(sidecar_config(config_id))
        controller = state.get_controller(config_id)
        controller.session.read_outcomes.append(error)
        if isinstance(error, OSError):
            controller.session.read_outcomes.append(error)

        record = await controller.refresh_point("value")
        snapshot = controller.snapshot()

        assert record["value"] == 42
        assert record["quality"] == "unavailable"
        assert record["error_code"] == error_code
        assert snapshot[counter] == 1
        assert "private /dev/serial detail" not in str(snapshot)
    finally:
        await state.remove_config(config_id)


@pytest.mark.anyio
async def test_failed_initial_config_leaves_no_ghost_bus_or_operational_surface(
    monkeypatch: pytest.MonkeyPatch,
    scripted_session_factory,
    sidecar_config: Callable[..., DeviceConfig],
) -> None:
    """A failed probe is absent from both lifecycle ownership and the HTTP API."""
    monkeypatch.setattr(state, "session_factory", scripted_session_factory)
    monkeypatch.setenv("PIPHI_MODBUS_SIDECAR_TOKEN", "internal")
    monkeypatch.setenv("PIPHI_ENV", "production")
    anchor = "test-profile-anchor"
    monkeypatch.setenv("PIPHI_MODBUS_PROFILE_TRUST_ANCHOR", anchor)
    scripted_session_factory.next_open_error = OSError("private adapter failure")
    config = sidecar_config("failed-initial")
    digest = profile_hash(config)
    config = config.model_copy(
        update={
            "profile_sha256": digest,
            "profile_signature": hmac.new(
                anchor.encode(), digest.encode(), hashlib.sha256
            ).hexdigest(),
        }
    )
    headers = {"Authorization": "Bearer internal"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://sidecar"
    ) as client:
        configured = await client.post(
            "/config", json=config.model_dump(mode="json"), headers=headers
        )
        snapshot = await client.get(
            "/v1/modbus/snapshot?config_id=failed-initial", headers=headers
        )

    assert configured.status_code == 409
    assert configured.json()["detail"] == {
        "error": "configuration_probe_failed",
        "reason": "serial_configuration_probe_failed",
    }
    assert "private adapter failure" not in configured.text
    assert snapshot.status_code == 404
    assert "failed-initial" not in state.controllers
    assert state.registry.get("failed-initial") is None
