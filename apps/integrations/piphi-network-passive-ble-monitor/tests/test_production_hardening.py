from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot
from piphi_runtime_testkit_python import build_runtime_headers

from piphi_network_passive_ble_monitor import lifecycle, state
from piphi_network_passive_ble_monitor.gateway import ConsumerMissing, ObservationPage
from piphi_network_passive_ble_monitor.main import app
from piphi_network_passive_ble_monitor.persistence import save_state
from piphi_network_passive_ble_monitor.privacy import redact
from piphi_network_passive_ble_monitor.schemas import DeviceConfig


@pytest.mark.anyio
async def test_only_health_is_public_and_auth_fails_closed(monkeypatch) -> None:
    state.runtime.auth.update(container_id="", internal_token="")
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runtime") as client:
        assert (await client.get("/health")).status_code == 200
        for path in ("/entities", "/diagnostics", "/state", "/events"):
            assert (await client.get(path)).status_code in {401, 503}


def test_recursive_redaction_and_bind_key_validation() -> None:
    value = {"nested": [{"gateway_token": "canary"}], "bind_key": "canary", "safe": "value"}
    assert "canary" not in json.dumps(redact(value))
    assert redact(value)["safe"] == "value"
    config = DeviceConfig(
        id="encrypted", gateway_url="https://gateway.test", gateway_token="token",
        device_handle="ble_00000000000000000000000000000001",
        bind_key="00112233445566778899aabbccddeeff",
    )
    assert "001122" not in repr(config)
    with pytest.raises(ValueError, match="32 hexadecimal"):
        DeviceConfig(
            id="bad", gateway_url="https://gateway.test", gateway_token="token",
            device_handle="ble_00000000000000000000000000000001", bind_key="plaintext",
        )


def test_persisted_last_good_state_is_owner_only_and_secret_free(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "state.json"
    save_state({"one": {"device_id": "device", "state": {"temperature_c": 20, "gateway_token": "canary"}}}, destination)
    content = destination.read_text()
    assert "canary" not in content
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700


class RestartingGateway:
    def __init__(self) -> None:
        self.registered = []
        self.calls = 0

    async def register(self, consumer_id, handle, bind_key=None):
        self.registered.append((consumer_id, handle, bind_key))

    async def unregister(self, _consumer_id):
        return None

    async def snapshot(self, _consumer_id, *, after=0):
        return ObservationPage((), after, True)

    async def observations(self, _consumer_id, *, after):
        self.calls += 1
        if self.calls == 1:
            raise ConsumerMissing("sidecar restarted")
        return ObservationPage((), after, True)

    async def close(self):
        return None


@pytest.mark.anyio
async def test_sidecar_restart_reregisters_scoped_consumer(monkeypatch) -> None:
    gateway = RestartingGateway()
    monkeypatch.setattr(state, "gateway_client", lambda _config: gateway)
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = DeviceConfig(
        id="restart", gateway_url="https://gateway.test", gateway_token="token",
        device_handle="ble_00000000000000000000000000000002",
    )
    await state.apply_config(config)
    try:
        initial_registrations = len(gateway.registered)
        await state.poll_config("restart")
        assert len(gateway.registered) == initial_registrations + 1
    finally:
        await state.remove_config("restart")


@pytest.mark.anyio
async def test_core_restart_restores_config_generation_and_last_good_state(monkeypatch) -> None:
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    config = DeviceConfig(
        id="core-restart", gateway_url="https://gateway.test", gateway_token="token",
        device_handle="ble_00000000000000000000000000000003",
    )
    device_id = state.make_entry(config)["device_id"]
    monkeypatch.setattr(
        state,
        "state_loader",
        lambda: {"core-restart": {"device_id": device_id, "state": {"temperature_c": 21.5}}},
    )

    async def fake_rehydrate(**kwargs) -> None:
        snapshot = RuntimeConfigSnapshot(container_id="container", generation=17).model_copy(
            update={"configs": [config]}
        )
        await kwargs["apply_snapshot"](snapshot)

    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    await lifecycle.startup_sync("runtime", "client")
    try:
        assert state.registry.ids() == ["core-restart"]
        assert state.registry.state_snapshots["core-restart"]["state"]["temperature_c"] == 21.5
        assert state.config_sync.get_current_generation() == 17
    finally:
        await state.remove_config("core-restart")


class SnapshotGateway:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def register(self, _consumer_id, _handle, _bind_key=None):
        return None

    async def unregister(self, _consumer_id):
        return None

    async def snapshot(self, _consumer_id, *, after=0):
        if self.fail:
            raise RuntimeError("snapshot rejected")
        return ObservationPage((), after, True)

    async def close(self):
        return None


@pytest.mark.anyio
async def test_multi_config_snapshot_rolls_back_atomically(monkeypatch) -> None:
    monkeypatch.setattr(state, "schedule_telemetry_delivery", lambda **_kwargs: None)
    monkeypatch.setattr(state, "gateway_client", lambda config: SnapshotGateway(fail=config.id == "second"))
    old = DeviceConfig(
        id="old", gateway_url="https://gateway.test", gateway_token="token",
        device_handle="ble_00000000000000000000000000000004",
    )
    await state.apply_config(old)
    state.config_sync.mark_generation(20)
    incoming = RuntimeConfigSnapshot(container_id="container", generation=21).model_copy(update={
        "configs": [
            DeviceConfig(
                id="first", gateway_url="https://gateway.test", gateway_token="token",
                device_handle="ble_00000000000000000000000000000005",
            ),
            DeviceConfig(
                id="second", gateway_url="https://gateway.test", gateway_token="token",
                device_handle="ble_00000000000000000000000000000006",
            ),
        ]
    })
    try:
        with pytest.raises(RuntimeError, match="snapshot rejected"):
            await state.apply_config_snapshot(incoming)
        assert state.registry.ids() == ["old"]
        assert state.config_sync.get_current_generation() == 20
    finally:
        for config_id in list(state.registry.ids()):
            await state.remove_config(config_id)
