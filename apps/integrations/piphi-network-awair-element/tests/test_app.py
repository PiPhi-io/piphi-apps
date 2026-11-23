from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from piphi_runtime_kit_python import RUNTIME_CONFIG_SNAPSHOT_PATH_ENV_NAME
from piphi_runtime_testkit_python import assert_telemetry_sent

from com_piphi_await_element.app import app
from com_piphi_await_element.contract.command import router as command_module
from com_piphi_await_element.contract.config import routes
from com_piphi_await_element.contract.discovery import discovery
from com_piphi_await_element.contract.health.router import diagnostics_report
from com_piphi_await_element.lib import lifespan
from com_piphi_await_element.lib.awair_client import (
    AwairLocalClient,
    AwairTransportError,
    fake_awair_transport,
    normalize_payload,
    resolve_local_host,
)
from com_piphi_await_element.lib.logging import configure_logging, redact
from com_piphi_await_element.lib.schemas import AwairElement
from com_piphi_await_element.lib.store import registry, runtime_context

ROOT = Path(__file__).resolve().parents[1]
READING = {
    "timestamp": "2026-05-13T14:55:28.665Z",
    "score": 55,
    "temp": 22.1,
    "humid": 47.5,
    "dew_point": 14.65,
    "abs_humid": 12.13,
    "co2": 612,
    "voc": 105,
    "pm25": 3,
}


class FakeClient:
    def __init__(self, readings=None) -> None:
        self.readings = list(readings or [READING, READING])
        self.closed = False

    async def latest(self):
        value = self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]
        if isinstance(value, Exception):
            raise value
        return normalize_payload(value)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_private_device_identity_and_address_are_not_logged(caplog) -> None:
    identity = "AWAIR-ELEM-PRIVATE123"
    private_address = "192.168.50.23"
    caplog.set_level(logging.INFO)
    configure_logging("INFO")

    listener = lifespan.ZeroConfGlobalListener(SimpleNamespace())
    lifespan.config[f"{identity}._http._tcp.local."] = {"addresses": [private_address]}
    listener.remove_service(None, "_http._tcp.local.", f"{identity}._http._tcp.local.")

    client = AwairLocalClient(
        configured_host=private_address,
        resolved_host=private_address,
        transport=fake_awair_transport(READING),
    )
    try:
        await client.latest()
    finally:
        await client.close()

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    assert identity not in caplog.text
    assert private_address not in caplog.text


@pytest.fixture(autouse=True)
async def reset_runtime(monkeypatch):
    monkeypatch.setenv("PIPHI_ALLOW_UNAUTHENTICATED", "true")
    yield
    for task in list(routes.runtime_data.tasks.values()):
        task.cancel()
    await asyncio.gather(*routes.runtime_data.tasks.values(), return_exceptions=True)
    for client in list(routes.runtime_data.clients.values()):
        await client.close()
    routes.runtime_data.configs.clear()
    routes.runtime_data.clients.clear()
    routes.runtime_data.tasks.clear()
    routes.runtime_data.locks.clear()
    routes.runtime_data.connector = AwairLocalClient.connect
    registry.entries.clear()
    registry.state_snapshots.clear()
    registry.recent_events.clear()
    runtime_context.auth.container_id = ""
    runtime_context.auth.internal_token = ""


@pytest.mark.anyio
async def test_auth_fails_closed_and_only_health_is_public(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_ALLOW_UNAUTHENTICATED", raising=False)
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        for path in ("/entities", "/diagnostics", "/discover", "/manifest.json"):
            assert (await client.get(path)).status_code == 503
        monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", "runtime-secret")
        assert (await client.get("/entities")).status_code == 401
        assert (
            await client.get(
                "/entities", headers={"X-PiPhi-Integration-Token": "runtime-secret"}
            )
        ).status_code == 200


@pytest.mark.anyio
async def test_refresh_command_requires_exact_configured_target(monkeypatch) -> None:
    device_id = routes.stable_device_id("AWAIR-ELEM-COMMAND")
    registry.set("command-config", {"config_id": "command-config", "device_id": device_id})

    async def refresh(config_id: str):
        return {"config_id": config_id, "device_id": device_id, "state": {"score": 55}}

    monkeypatch.setattr(command_module, "trigger_refresh", refresh)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post("/command", json={"command": "refresh"})
        mismatch = await client.post(
            "/command",
            json={
                "command": "refresh",
                "target": {"config_id": "command-config", "device_id": "wrong"},
            },
        )
        accepted = await client.post(
            "/command",
            json={
                "command": "refresh",
                "target": {"config_id": "command-config", "device_id": device_id},
            },
            headers={"X-PiPhi-Idempotency-Key": "awair-read-only-refresh-1"},
        )
    assert missing.status_code == 400
    assert mismatch.status_code == 409
    assert accepted.status_code == 200
    assert accepted.json()["state"]["score"] == 55


@pytest.mark.anyio
async def test_host_policy_rejects_public_loopback_mixed_dns_and_url_syntax(monkeypatch) -> None:
    for host in ("8.8.8.8", "127.0.0.1", "http://192.168.1.2", "user@192.168.1.2"):
        with pytest.raises(AwairTransportError):
            await resolve_local_host(host)

    async def mixed(*_args, **_kwargs):
        return [(2, 1, 6, "", ("192.168.1.10", 80)), (2, 1, 6, "", ("8.8.4.4", 80))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", mixed)
    with pytest.raises(AwairTransportError, match="non_local_address"):
        await resolve_local_host("awair.local")


@pytest.mark.anyio
async def test_fake_transport_is_deterministic_redirect_free_and_socket_free(monkeypatch) -> None:
    async def pinned(_host: str) -> str:
        return "192.168.1.20"

    monkeypatch.setattr(
        "com_piphi_await_element.lib.awair_client.resolve_local_host", pinned
    )
    first = await AwairLocalClient.connect(
        "awair.local", transport=fake_awair_transport(READING)
    )
    second = await AwairLocalClient.connect(
        "awair.local", transport=fake_awair_transport(READING)
    )
    assert await first.latest() == await second.latest()
    assert "power_on" not in await first.latest()
    await first.close()
    await second.close()

    client = AwairLocalClient(
        configured_host="awair.local",
        resolved_host="192.168.1.20",
        transport=fake_awair_transport({}, status_code=302),
    )
    with pytest.raises(AwairTransportError, match="redirect_rejected"):
        await client.latest()
    await client.close()


@pytest.mark.anyio
async def test_connect_before_save_stable_identity_and_failed_change_rollback() -> None:
    original_client = FakeClient()

    async def connect_ok(_host: str):
        return original_client

    routes.runtime_data.connector = connect_ok
    config = AwairElement(
        id="bedroom-config",
        device_ip="192.168.1.20",
        device_identity="AWAIR-ELEM-1450C8",
    )
    await routes.apply_device_config(config)
    entry = registry.get("bedroom-config")
    assert entry is not None
    assert entry["device_id"] == routes.stable_device_id("awair-elem-1450c8")
    assert "device_ip" not in entry

    async def connect_failed(_host: str):
        raise AwairTransportError("unreachable")

    routes.runtime_data.connector = connect_failed
    with pytest.raises(HTTPException) as raised:
        await routes.apply_device_config(config.model_copy(update={"device_ip": "192.168.1.21"}))
    assert raised.value.detail == {"error": "unreachable"}
    assert routes.runtime_data.clients["bedroom-config"] is original_client
    assert routes.runtime_data.configs["bedroom-config"].device_ip == "192.168.1.20"
    assert original_client.closed is False


@pytest.mark.anyio
async def test_runtime_testkit_receives_only_validated_awair_telemetry(
    mock_core, monkeypatch
) -> None:
    client = FakeClient()

    async def connect(_host: str):
        return client

    routes.runtime_data.connector = connect
    monkeypatch.setattr(routes.telemetry_client, "core_base_url", mock_core.base_url)
    runtime_context.auth.update(container_id="runtime-awair", internal_token="runtime-secret")
    config = AwairElement(
        id="telemetry-config",
        config_id="telemetry-config",
        container_id="runtime-awair",
        device_ip="192.168.1.20",
        device_identity="AWAIR-ELEM-TELEMETRY",
    )
    await routes.apply_device_config(config)
    for _attempt in range(100):
        if mock_core.telemetry_requests:
            break
        await asyncio.sleep(0.01)
    request = assert_telemetry_sent(
        mock_core,
        device_id=routes.stable_device_id("AWAIR-ELEM-TELEMETRY"),
    )
    assert request.json_body["metrics"]["temperature"] == 22.1
    assert request.json_body["metrics"]["score"] == 55
    assert "power_on" not in request.json_body["metrics"]
    headers = {key.lower(): value for key, value in request.headers.items()}
    assert headers["x-container-id"] == "runtime-awair"
    assert headers["x-piphi-integration-token"] == "runtime-secret"


@pytest.mark.anyio
async def test_commit_failure_rolls_back_and_closes_candidate(monkeypatch) -> None:
    original, candidate = FakeClient(), FakeClient()
    clients = iter([original, candidate])

    async def connect(_host: str):
        return next(clients)

    routes.runtime_data.connector = connect
    config = AwairElement(id="rollback", device_ip="192.168.1.20", device_identity="AWAIR-ELEM-A")
    await routes.apply_device_config(config)
    original_entry = registry.get("rollback")

    def fail_publish(*_args, **_kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(routes, "schedule_telemetry_delivery", fail_publish)
    with pytest.raises(RuntimeError, match="commit failed"):
        await routes.apply_device_config(config.model_copy(update={"device_ip": "192.168.1.21"}))
    assert registry.get("rollback") is original_entry
    assert routes.runtime_data.clients["rollback"] is original
    assert candidate.closed is True


@pytest.mark.anyio
async def test_stale_last_good_recovery_removal_and_bounded_retry(monkeypatch) -> None:
    client = FakeClient([READING, AwairTransportError("unreachable"), READING])

    async def connect(_host: str):
        return client

    routes.runtime_data.connector = connect
    config = AwairElement(id="recovery", device_ip="192.168.1.20", device_identity="AWAIR-ELEM-B")
    await routes.apply_device_config(config)
    with pytest.raises(HTTPException):
        await routes.trigger_refresh("recovery")
    stale = registry.state_snapshots["recovery"]["state"]
    assert stale["stale"] is True and stale["temperature"] == 22.1
    restored = await routes.trigger_refresh("recovery")
    assert restored["state"]["stale"] is False
    assert await routes.remove_device_config("recovery") is True
    assert client.closed is True and registry.get("recovery") is None

    calls = 0
    registry.set("bounded", {"config_id": "bounded"})
    routes.runtime_data.configs["bounded"] = config.model_copy(update={"id": "bounded"})

    async def no_wait(_delay):
        return None

    async def fail_three(_config_id):
        nonlocal calls
        calls += 1
        if calls == 3:
            registry.remove("bounded")
        raise HTTPException(status_code=503)

    monkeypatch.setattr(routes.asyncio, "sleep", no_wait)
    monkeypatch.setattr(routes, "trigger_refresh", fail_three)
    await routes._poll("bounded")
    assert calls == 3


@pytest.mark.anyio
async def test_restart_rehydrates_snapshot(monkeypatch) -> None:
    seen = {}

    async def apply_snapshot(snapshot):
        seen["snapshot"] = snapshot

    async def rehydrate(**kwargs):
        seen["model"] = kwargs["config_model"]
        await kwargs["apply_snapshot"](SimpleNamespace(configs=[]))
        return SimpleNamespace(
            snapshot_applied=True,
            snapshot_config_count=0,
            snapshot_generation=1,
            core_applied=False,
            core_error=None,
            missing_runtime_auth=True,
            core_attempted=False,
        )

    monkeypatch.setattr(lifespan, "restore_runtime_config_snapshot", apply_snapshot)
    monkeypatch.setattr(lifespan, "rehydrate_runtime_configs", rehydrate)
    await lifespan.startup_sync(runtime_context, "core-client")
    assert seen["model"] is AwairElement
    assert seen["snapshot"].configs == []


@pytest.mark.anyio
async def test_offline_restart_restores_config_and_recovers(monkeypatch) -> None:
    async def offline(_host: str):
        raise AwairTransportError("unreachable")

    routes.runtime_data.connector = offline
    config = AwairElement(
        id="restart-offline",
        device_ip="192.168.1.20",
        device_identity="AWAIR-ELEM-RESTORE",
    )
    response = await routes.restore_device_config(config)
    assert response["metadata"]["restored_offline"] is True
    assert registry.get("restart-offline")["availability"] == "unavailable"

    recovered = FakeClient()

    async def online(_host: str):
        return recovered

    routes.runtime_data.connector = online
    state = await routes.trigger_refresh("restart-offline")
    assert state["state"]["available"] is True
    assert registry.get("restart-offline")["availability"] == "online"
    assert any(event["event_type"] == "device.restored" for event in registry.recent_events)


@pytest.mark.anyio
async def test_discovery_identity_is_stable_and_truthful(monkeypatch) -> None:
    async def verify(_host: str):
        return FakeClient()

    monkeypatch.setattr(discovery, "connector", verify)
    async def connect(_host: str):
        return FakeClient()

    monkeypatch.setattr(discovery, "connector", connect)
    monkeypatch.setattr(
        discovery,
        "config",
        {
            "AWAIR-ELEM-1450C8._http._tcp.local.": {"addresses": ["192.168.1.20"]},
            "Awair Maybe._http._tcp.local.": {"addresses": ["192.168.1.21"]},
            "AWAIR-ELEM-PUBLIC._http._tcp.local.": {"addresses": ["8.8.8.8"]},
        },
    )
    devices = (await discovery.get_discovered_devices()).model_dump()["devices"]
    assert devices == [{
        "id": "AWAIR-ELEM-1450C8",
        "device_id": "AWAIR-ELEM-1450C8",
        "device_identity": "AWAIR-ELEM-1450C8",
        "device_ip": "192.168.1.20",
        "make": "Awair",
        "model": "Element",
        "name": "AWAIR-ELEM-1450C8",
        "port": 80,
    }]


def test_recursive_redaction_and_privacy_safe_diagnostics() -> None:
    value = {"nested": [{"api_token": "secret", "safe": "ok"}], "password_hint": "hidden"}
    assert redact(value) == {
        "nested": [{"api_token": "[REDACTED]", "safe": "ok"}],
        "password_hint": "[REDACTED]",
    }


@pytest.mark.anyio
async def test_diagnostics_are_aggregate_only() -> None:
    registry.set(
        "bedroom-192.168.1.20",
        {
            "config_id": "bedroom-192.168.1.20",
            "device_id": "awair-element:private-identity",
            "availability": "online",
        },
    )
    serialized = (await diagnostics_report()).model_dump_json()
    assert "192.168.1.20" not in serialized
    assert "private-identity" not in serialized
    assert '"online":1' in serialized


def test_manifest_catalog_and_release_contracts_are_consistent() -> None:
    manifest = json.loads((ROOT / "src/manifest.json").read_text())
    app_meta = json.loads((ROOT / "piphi-app.json").read_text())
    catalog = json.loads((ROOT / "capability-catalog.json").read_text())
    behaviors = json.loads((ROOT / "src/behaviors.json").read_text())
    assert manifest["version"] == app_meta["packages"][0]["version"] == "0.1.15"
    assert manifest["identity"]["fields"] == ["device_identity"]
    assert set(manifest["commands"]) == {"refresh"}
    runtime = manifest["runtime"]["linux"]["container"]
    assert RUNTIME_CONFIG_SNAPSHOT_PATH_ENV_NAME == "PIPHI_CONFIG_SNAPSHOT_PATH"
    assert runtime["environment"][RUNTIME_CONFIG_SNAPSHOT_PATH_ENV_NAME] == (
        "/var/lib/piphi/configs.json"
    )
    assert any(
        volume["container"] == "/var/lib/piphi" and volume["mode"] == "rw"
        for volume in runtime["volumes"]
    )
    assert [action["id"] for action in behaviors["devices"][0]["actions"]] == ["refresh_readings"]
    assert behaviors["templates"] == []
    implemented = next(entry for entry in catalog["entries"] if entry["status"] == "implemented")
    assert set(implemented["state"]) <= set(manifest["capabilities"])
    assert implemented["actions"] == ["refresh"]


def test_payload_validation_drops_unknowns_and_rejects_fabricated_values() -> None:
    normalized = normalize_payload({**READING, "unknown_vendor_field": 123})
    assert "unknown_vendor_field" not in normalized
    assert normalized["temperature"] == 22.1 and "temp" not in normalized
    with pytest.raises(AwairTransportError, match="invalid_response"):
        normalize_payload({"temp": float("nan")})
    with pytest.raises(AwairTransportError, match="invalid_response"):
        normalize_payload({"score": 101})
    with pytest.raises(AwairTransportError, match="invalid_response"):
        normalize_payload({"timestamp": "only-a-timestamp"})
