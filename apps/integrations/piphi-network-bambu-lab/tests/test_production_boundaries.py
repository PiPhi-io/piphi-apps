from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from piphi_network_bambu_lab import lifecycle, state
from piphi_network_bambu_lab.main import app
from piphi_network_bambu_lab.redaction import redact
from piphi_network_bambu_lab.schemas import SUPPORTED_MODELS, DeviceConfig


def real_config(config_id: str = "printer", **updates) -> DeviceConfig:
    values = {
        "id": config_id,
        "host": "192.168.1.50",
        "serial": "ABC123456",
        "model": "P1S",
        "access_code": "private-access-code",
        "developer_mode_acknowledged": True,
    }
    values.update(updates)
    return DeviceConfig.model_validate(values)


@pytest.mark.anyio
async def test_auth_fails_closed_and_only_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 503
        monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
        assert (await client.get("/diagnostics")).status_code == 401
        assert (
            await client.get(
                "/diagnostics", headers={"X-PiPhi-Integration-Token": "runtime-secret"}
            )
        ).status_code == 200


def test_recursive_redaction_and_secret_representation() -> None:
    config = real_config()
    assert isinstance(config.access_code, SecretStr)
    assert "private-access-code" not in repr(config)
    assert redact({"nested": [{"access_code": config.access_code}], "ok": "visible"}) == {
        "nested": [{"access_code": "********"}],
        "ok": "visible",
    }


def test_supported_model_matrix_is_explicit_and_unknown_models_fail() -> None:
    assert SUPPORTED_MODELS == ("A1", "A1 mini", "P1P", "P1S", "X1", "X1 Carbon", "X1E")
    with pytest.raises(ValueError, match="unsupported printer model"):
        real_config(model="Future Printer")


@pytest.mark.anyio
async def test_failed_reconfiguration_preserves_working_session(mock_mqtt, monkeypatch) -> None:
    original = real_config("rollback")
    await state.apply_config(original)
    old_session = state._sessions[original.id]
    old_entry = state.registry.get(original.id)

    def fail_start(_self):
        raise OSError("connect setup failed")

    monkeypatch.setattr(mock_mqtt, "start", fail_start)
    with pytest.raises(OSError, match="connect setup failed"):
        await state.apply_config(original.model_copy(update={"alias": "replacement"}))
    assert state._sessions[original.id] is old_session
    assert state.registry.get(original.id) is old_entry
    await state.remove_config(original.id)


@pytest.mark.anyio
async def test_identity_is_serial_stable_and_duplicate_serial_fails(mock_mqtt) -> None:
    first = real_config("first", host="192.168.1.50")
    await state.apply_config(first)
    first_id = state.registry.get(first.id)["device_id"]
    assert state.make_entry(first.model_copy(update={"host": "192.168.1.51"}))["device_id"] == first_id
    with pytest.raises(HTTPException) as duplicate:
        await state.apply_config(real_config("second", host="192.168.1.52"))
    assert duplicate.value.detail == {"error": "device_already_configured"}
    await state.remove_config(first.id)


@pytest.mark.anyio
async def test_stale_last_good_transition_is_deduplicated_and_restores(mock_mqtt) -> None:
    config = real_config("stale")
    await state.apply_config(config)
    await state.record_report(
        config.id, {"print": {"command": "push_status", "gcode_state": "RUNNING", "mc_percent": 44}}
    )
    await state.mark_offline(config.id, "transport_lost")
    await state.mark_offline(config.id, "transport_lost")
    stale = state.current_state(config.id)
    assert stale["print_progress_percent"] == 44
    assert stale["stale"] is True
    assert [e["event_type"] for e in state.registry.recent_events].count("device.unavailable") == 1
    await state.record_report(
        config.id, {"print": {"command": "push_status", "gcode_state": "RUNNING", "mc_percent": 45}}
    )
    assert state.current_state(config.id)["stale"] is False
    assert [e["event_type"] for e in state.registry.recent_events].count("device.restored") == 1
    await state.remove_config(config.id)


@pytest.mark.anyio
async def test_masked_secret_reuses_stored_access_code(mock_mqtt) -> None:
    config = real_config("masked")
    await state.apply_config(config)
    await state.apply_config(config.model_copy(update={"access_code": SecretStr("********")}))
    stored = state.runtime_data.configs[config.id].access_code
    assert stored is not None and stored.get_secret_value() == "private-access-code"
    await state.remove_config(config.id)


@pytest.mark.anyio
async def test_startup_rehydrates_core_configuration(monkeypatch, mock_mqtt) -> None:
    seen = {}

    async def apply_snapshot(**kwargs):
        await kwargs["apply_config"](real_config("restored"))

    async def rehydrate(**kwargs):
        seen["model"] = kwargs["config_model"]
        await kwargs["apply_snapshot"](SimpleNamespace(configs=[]))

    monkeypatch.setattr(lifecycle, "config_sync", SimpleNamespace(apply_snapshot=apply_snapshot))
    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", rehydrate)
    await lifecycle.startup_sync("runtime", "client")
    assert seen["model"] is DeviceConfig
    assert state.registry.get("restored") is not None
    await state.remove_config("restored")


@pytest.mark.anyio
async def test_diagnostics_do_not_expose_host_serial_or_access_code(mock_mqtt) -> None:
    config = real_config("privacy")
    await state.apply_config(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        text = (await client.get("/diagnostics")).text
    assert config.host not in text
    assert config.serial not in text
    assert config.access_code.get_secret_value() not in text
    await state.remove_config(config.id)
