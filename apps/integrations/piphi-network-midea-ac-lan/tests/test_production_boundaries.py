from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from piphi_network_midea_ac_lan import lifecycle, state
from piphi_network_midea_ac_lan.main import app
from piphi_network_midea_ac_lan.midea_client import (
    MideaLanClient,
    MideaSetupError,
    resolve_local_host,
)
from piphi_network_midea_ac_lan.schemas import DeviceConfig


class FakeClient:
    def __init__(
        self, hardware_id: str = "midea-production", *, fail_refresh: bool = False
    ) -> None:
        self.hardware_id = hardware_id
        self.fail_refresh = fail_refresh
        self.closed = False

    async def refresh(self) -> dict:
        if self.fail_refresh:
            raise ConnectionError("transport unavailable")
        return {"connected": True, "power": True, "indoor_temperature_c": 23.0}

    async def execute(self, _command: str, _args: dict) -> dict:
        return await self.refresh()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_auth_fails_closed_and_only_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/entities")).status_code == 503

        monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
        assert (await client.get("/entities")).status_code == 401
        response = await client.get(
            "/entities",
            headers={"X-PiPhi-Integration-Token": "runtime-secret"},
        )
        assert response.status_code == 200


@pytest.mark.anyio
async def test_masked_credentials_reuse_stored_secrets(monkeypatch) -> None:
    calls: list[dict] = []

    async def connect(**kwargs):
        calls.append(kwargs)
        return FakeClient()

    state.runtime_data.connector = connect
    original = DeviceConfig(
        id="secret-test",
        host="192.168.1.20",
        token="private-token",
        key="private-key",
    )
    await state.apply_config(original)
    replacement = original.model_copy(
        update={
            "alias": "Bedroom",
            "token": SecretStr("********"),
            "key": SecretStr("********"),
        }
    )
    await state.apply_config(replacement)

    stored = state.runtime_data.configs["secret-test"]
    assert stored.token is not None and stored.token.get_secret_value() == "private-token"
    assert stored.key is not None and stored.key.get_secret_value() == "private-key"
    assert calls[-1]["token"] == "private-token"
    assert calls[-1]["key"] == "private-key"
    assert "private-token" not in repr(stored)


@pytest.mark.anyio
async def test_failed_reconfiguration_preserves_working_runtime() -> None:
    original_client = FakeClient()

    async def connect_ok(**_kwargs):
        return original_client

    state.runtime_data.connector = connect_ok
    original = DeviceConfig(id="rollback-test", host="192.168.1.21", alias="Original")
    await state.apply_config(original)
    original_entry = state.registry.get("rollback-test")

    async def connect_failed(**_kwargs):
        raise MideaSetupError("invalid_auth")

    state.runtime_data.connector = connect_failed
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(original.model_copy(update={"alias": "Replacement"}))

    assert raised.value.detail == {"error": "invalid_auth"}
    assert state.registry.get("rollback-test") is original_entry
    assert state.runtime_data.clients["rollback-test"] is original_client
    assert state.runtime_data.configs["rollback-test"].alias == "Original"
    assert original_client.closed is False


@pytest.mark.anyio
async def test_commit_failure_rolls_back_reconfiguration(monkeypatch) -> None:
    original_client = FakeClient()
    candidate_client = FakeClient()
    clients = iter([original_client, candidate_client])

    async def connect(**_kwargs):
        return next(clients)

    state.runtime_data.connector = connect
    original = DeviceConfig(id="commit-rollback-test", host="192.168.1.36", alias="Original")
    await state.apply_config(original)
    original_entry = state.registry.get(original.id)
    original_state = state.registry.state_snapshots[original.id]

    def fail_telemetry(**_kwargs):
        raise RuntimeError("telemetry scheduler unavailable")

    monkeypatch.setattr(state, "schedule_telemetry_delivery", fail_telemetry)
    with pytest.raises(RuntimeError, match="telemetry scheduler unavailable"):
        await state.apply_config(original.model_copy(update={"alias": "Replacement"}))

    assert state.registry.get(original.id) is original_entry
    assert state.registry.state_snapshots[original.id] is original_state
    assert state.runtime_data.configs[original.id].alias == "Original"
    assert state.runtime_data.clients[original.id] is original_client
    assert original_client.closed is False
    assert candidate_client.closed is True


@pytest.mark.anyio
async def test_masked_credentials_without_a_stored_pair_fail_closed() -> None:
    masked = DeviceConfig(
        id="missing-secret-test",
        host="192.168.1.31",
        token="********",
        key="********",
    )
    with pytest.raises(HTTPException) as raised:
        await state.apply_config(masked)
    assert raised.value.detail == {"error": "credentials_required"}


@pytest.mark.anyio
async def test_duplicate_and_changed_hardware_identity_are_rejected() -> None:
    clients = iter(
        [FakeClient("same-device"), FakeClient("same-device"), FakeClient("other-device")]
    )

    async def connect(**_kwargs):
        return next(clients)

    state.runtime_data.connector = connect
    await state.apply_config(DeviceConfig(id="first", host="192.168.1.22"))

    with pytest.raises(HTTPException) as duplicate:
        await state.apply_config(DeviceConfig(id="second", host="192.168.1.23"))
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail == {"error": "device_already_configured"}

    with pytest.raises(HTTPException) as changed:
        await state.apply_config(DeviceConfig(id="first", host="192.168.1.24"))
    assert changed.value.status_code == 409
    assert changed.value.detail == {"error": "device_identity_mismatch"}


@pytest.mark.anyio
async def test_public_and_mixed_dns_destinations_are_rejected(monkeypatch) -> None:
    with pytest.raises(MideaSetupError, match="non_local_address"):
        await resolve_local_host("8.8.8.8")

    loop = asyncio.get_running_loop()

    async def mixed_addresses(*_args, **_kwargs):
        return [
            (2, 1, 6, "", ("192.168.1.30", 0)),
            (2, 1, 6, "", ("8.8.4.4", 0)),
        ]

    monkeypatch.setattr(loop, "getaddrinfo", mixed_addresses)
    with pytest.raises(MideaSetupError, match="non_local_address"):
        await resolve_local_host("ac.example.invalid")


@pytest.mark.anyio
async def test_refresh_marks_state_stale_backs_off_and_restores() -> None:
    initial = FakeClient()

    async def connect_initial(**_kwargs):
        return initial

    state.runtime_data.connector = connect_initial
    config = DeviceConfig(id="recovery-test", host="192.168.1.25", poll_interval_seconds=5)
    await state.apply_config(config)
    entry = state.registry.get("recovery-test")
    assert entry is not None
    initial.fail_refresh = True

    unavailable = await state.refresh_entry(entry)
    assert unavailable["stale"] is True
    assert unavailable["available"] is False
    assert unavailable["indoor_temperature_c"] == 23.0
    assert entry["next_poll_at"] >= time.monotonic() + 9
    assert [event["event_type"] for event in state.registry.recent_events].count(
        "device.unavailable"
    ) == 1

    recovered = FakeClient()

    async def connect_recovered(**_kwargs):
        return recovered

    state.runtime_data.connector = connect_recovered
    restored = await state.refresh_entry(entry)
    assert restored["stale"] is False
    assert restored["available"] is True
    assert entry["consecutive_failures"] == 0
    assert any(event["event_type"] == "device.restored" for event in state.registry.recent_events)


@pytest.mark.anyio
async def test_command_transport_failure_marks_state_unavailable() -> None:
    client = FakeClient()

    async def connect(**_kwargs):
        return client

    state.runtime_data.connector = connect
    await state.apply_config(
        DeviceConfig(
            id="command-failure-test",
            host="192.168.1.32",
            controls_enabled=True,
        )
    )
    entry = state.registry.get("command-failure-test")
    assert entry is not None
    client.fail_refresh = True
    with pytest.raises(RuntimeError, match="unavailable"):
        await state.execute_command(entry, "set_power", {"power": False})
    snapshot = state.registry.state_snapshots["command-failure-test"]["state"]
    assert snapshot["stale"] is True
    assert snapshot["available"] is False


@pytest.mark.anyio
async def test_authentication_failure_stops_automatic_retries() -> None:
    client = FakeClient()

    async def connect(**_kwargs):
        return client

    state.runtime_data.connector = connect
    await state.apply_config(DeviceConfig(id="reauth-test", host="192.168.1.35"))
    entry = state.registry.get("reauth-test")
    assert entry is not None

    class AuthenticationError(Exception):
        pass

    async def auth_failure() -> dict:
        raise AuthenticationError

    client.refresh = auth_failure  # type: ignore[method-assign]
    unavailable = await state.refresh_entry(entry)
    assert unavailable["error_category"] == "invalid_auth"
    assert entry["availability"] == "reauth_required"
    assert entry["next_poll_at"] == float("inf")


@pytest.mark.anyio
async def test_commands_require_an_exact_configured_target() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post("/command", json={"command": "refresh"})
        assert missing.status_code == 400

        await client.post("/config", json={"id": "target-test", "host": "192.168.1.26"})
        mismatch = await client.post(
            "/command",
            json={
                "command": "refresh",
                "target": {"config_id": "target-test", "device_id": "wrong-device"},
            },
        )
        assert mismatch.status_code == 200
        assert mismatch.json()["status"] == "failed"
        assert "does not match" in mismatch.json()["error"]


@pytest.mark.anyio
async def test_startup_rehydrates_core_configuration(monkeypatch) -> None:
    seen: dict = {}

    async def apply_snapshot(**kwargs):
        seen["active_config_ids"] = kwargs["active_config_ids"]
        await kwargs["apply_config"](DeviceConfig(id="restored-test", host="192.168.1.27"))

    async def rehydrate(**kwargs):
        seen["model"] = kwargs["config_model"]
        await kwargs["apply_snapshot"](SimpleNamespace(configs=[]))

    monkeypatch.setattr(
        lifecycle,
        "config_sync",
        SimpleNamespace(apply_snapshot=apply_snapshot),
    )
    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", rehydrate)
    await lifecycle.startup_sync("runtime-context", "core-client")

    assert seen["model"] is DeviceConfig
    assert state.registry.get("restored-test") is not None


@pytest.mark.anyio
async def test_diagnostics_never_expose_network_or_credentials() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/config",
            json={
                "id": "privacy-test",
                "host": "192.168.1.28",
                "token": "private-token",
                "key": "private-key",
            },
        )
        response = await client.get("/diagnostics")
    serialized = response.text
    assert "private-token" not in serialized
    assert "private-key" not in serialized
    assert "192.168.1.28" not in serialized


@pytest.mark.anyio
async def test_simulation_is_deterministic_and_does_not_resolve_network(monkeypatch) -> None:
    async def forbidden_resolution(_host: str) -> str:
        raise AssertionError("simulation must not resolve a network destination")

    monkeypatch.setattr(
        "piphi_network_midea_ac_lan.midea_client.resolve_local_host",
        forbidden_resolution,
    )
    first = await MideaLanClient.connect(host="simulation://bedroom", device_id=123)
    second = await MideaLanClient.connect(host="simulation://bedroom", device_id=123)
    assert first.hardware_id == second.hardware_id
    assert await first.refresh() == await second.refresh()


@pytest.mark.anyio
async def test_discovery_is_empty_without_input_and_returns_verified_simulation() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        empty = await client.post("/discover", json={"inputs": {}})
        found = await client.post(
            "/discover",
            json={"inputs": {"host": "simulation://discovery", "midea_device_id": 44}},
        )
    assert empty.status_code == 200
    assert empty.json()["devices"] == []
    assert found.status_code == 200
    assert found.json()["devices"][0]["id"].startswith("midea-")


@pytest.mark.anyio
async def test_config_removal_and_runtime_state_routes() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json={"id": "route-test", "host": "192.168.1.29"})
        current = await client.get("/state")
        removed = await client.post("/deconfigure", json={"config_id": "route-test"})
        missing = await client.post("/deconfigure", json={})
        removed_again = await client.post("/deconfigure/route-test")
    assert current.status_code == 200
    assert "route-test" in current.json()["entries"]
    assert removed.status_code == 200
    assert removed.json()["removed"] is True
    assert missing.json() == {"ok": False, "reason": "missing config_id"}
    assert removed_again.json()["removed"] is False


@pytest.mark.anyio
async def test_core_snapshot_replaces_active_configuration() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/config", json={"id": "old-config", "host": "192.168.1.33"})
        response = await client.post(
            "/config/sync",
            json={
                "container_id": "runtime-test",
                "generation": 2,
                "configs": [{"id": "new-config", "host": "192.168.1.34"}],
                "deleted_config_ids": ["old-config"],
            },
        )
    assert response.status_code == 200
    assert response.json()["applied"] == ["new-config"]
    assert response.json()["removed"] == ["old-config"]
