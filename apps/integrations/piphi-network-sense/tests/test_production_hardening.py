from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot, build_runtime_auth_headers

from piphi_network_sense import lifecycle
from piphi_network_sense.main import app
from piphi_network_sense.schemas import DeviceConfig
from piphi_network_sense.security import REDACTED, redact
from piphi_network_sense.sense_client import SenseAuthStore, StoredSenseAuth
from piphi_network_sense.sense_client import SenseAuthenticationError
from piphi_network_sense.service import SenseRuntimeService, _daily_period


TOKEN = "production-boundary-test-token"
HEADERS = dict(build_runtime_auth_headers(container_id="sense-test", internal_token=TOKEN))


@pytest.mark.anyio
async def test_only_health_is_public_and_missing_auth_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", raising=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        for path in ("/diagnostics", "/contract", "/state", "/entities", "/events", "/docs", "/openapi.json"):
            assert (await client.get(path)).status_code == 503
        monkeypatch.setenv("PIPHI_INTEGRATION_INTERNAL_TOKEN", TOKEN)
        assert (await client.get("/contract")).status_code == 401
        assert (await client.get("/contract", headers=HEADERS)).status_code == 200


def test_recursive_redaction_covers_nested_tokens_and_inline_values() -> None:
    canary = "canary-private-value"
    payload = {
        "nested": [{"access_token": canary, "safe": f"token={canary}"}],
        "password": canary,
        "message": f"authorization={canary}",
    }
    sanitized = redact(payload, secrets=(canary,))
    assert canary not in json.dumps(sanitized)
    assert sanitized["password"] == REDACTED
    assert sanitized["nested"][0]["safe"] == "token=[redacted]"


def test_auth_store_is_atomic_private_and_removable(tmp_path: Path) -> None:
    path = tmp_path / "private" / "sense-auth.json"
    store = SenseAuthStore(path)
    auth = StoredSenseAuth("access", "refresh", "user", "monitor", "device")
    store.save("account", auth)
    assert store.load("account") == auth
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    store.remove("account")
    assert store.load("account") is None


class Registry:
    def __init__(self) -> None:
        self.state_snapshots: dict = {}

    def update_state(self, config_id, state, *, device_id):
        self.state_snapshots[config_id] = {"state": state, "device_id": device_id}


class Client:
    def __init__(self, monitor_id: str, *, fail_auth: bool = False) -> None:
        self.monitor_id = monitor_id
        self.fail_auth = fail_auth
        self.closed = False

    async def authenticate(self, _config) -> None:
        if self.fail_auth:
            raise RuntimeError("credential canary must not replace live session")

    async def read(self, *, include_trends: bool):
        from piphi_network_sense.sense_client import SenseReading

        return SenseReading(
            monitor_id=self.monitor_id,
            time_zone="America/New_York",
            active_power_w=100.0,
            active_solar_power_w=0.0,
            daily_usage_kwh=1.0,
            daily_production_kwh=0.0,
        )

    async def close(self) -> None:
        self.closed = True


def config(password: str) -> DeviceConfig:
    return DeviceConfig(id="account", email="owner@example.com", password=password, poll_interval_seconds=3600)


@pytest.mark.anyio
async def test_reconfigure_authenticates_before_replacing_active_session(monkeypatch) -> None:
    monkeypatch.setattr("piphi_network_sense.service.schedule_telemetry_delivery", lambda **_kwargs: None)
    clients = [Client("monitor-immutable"), Client("monitor-immutable", fail_auth=True)]
    service = SenseRuntimeService(
        registry=Registry(),
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
        client_factory=lambda: clients.pop(0),
    )
    first_entry = {"config_id": "account", "device_id": "temporary"}
    await service.configure(config("first-secret"), first_entry)
    with pytest.raises(RuntimeError):
        await service.configure(
            config("replacement-secret"),
            {"config_id": "account", "device_id": "temporary"},
        )
    assert service.active_config_id == "account"
    assert first_entry["device_id"] == "monitor-immutable"
    assert service._active is not None and service._active.client.closed is False
    await service.close()


@pytest.mark.anyio
async def test_auth_failure_marks_only_realtime_immediately_stale_and_blocks_retry(monkeypatch) -> None:
    monkeypatch.setattr("piphi_network_sense.service.schedule_telemetry_delivery", lambda **_kwargs: None)
    registry = Registry()
    client = Client("monitor-immutable")
    service = SenseRuntimeService(
        registry=registry,
        runtime=SimpleNamespace(process_state=object(), auth=object()),
        telemetry=object(),
        client_factory=lambda: client,
    )
    await service.configure(config("first-secret"), {"config_id": "account", "device_id": "temporary"})

    async def rejected_read(*, include_trends: bool):
        raise SenseAuthenticationError("provider detail and credential canary are hidden")

    client.read = rejected_read  # type: ignore[method-assign]
    with pytest.raises(SenseAuthenticationError):
        await service.refresh()
    failed = registry.state_snapshots["account"]["state"]
    assert failed["freshness"]["realtime"]["stale"] is True
    assert failed["freshness"]["daily_trends"]["stale"] is False
    assert failed["retry"]["blocked_until_reconfigure"] is True
    assert failed["reauth_required"] is True
    await service.close()


@pytest.mark.anyio
async def test_startup_rehydrates_core_managed_configuration(monkeypatch) -> None:
    captured = {}

    async def fake_rehydrate(**kwargs):
        captured.update(kwargs)

    apply_snapshot = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(lifecycle, "rehydrate_runtime_configs", fake_rehydrate)
    monkeypatch.setattr(lifecycle, "config_sync", SimpleNamespace(apply_snapshot=apply_snapshot))
    await lifecycle.startup_sync("runtime", "client")
    assert captured["config_model"] is DeviceConfig
    snapshot = RuntimeConfigSnapshot(container_id="sense-test", configs=[])
    await captured["apply_snapshot"](snapshot)
    assert apply_snapshot.await_args.kwargs["snapshot"] is snapshot


def test_daily_period_uses_provider_local_calendar_boundaries() -> None:
    from datetime import UTC, datetime

    period = _daily_period("America/New_York", datetime(2026, 11, 1, 12, tzinfo=UTC))["daily"]
    assert period["kind"] == "provider_local_calendar_day"
    assert period["time_zone"] == "America/New_York"
    assert period["start"].startswith("2026-11-01T00:00:00")
    assert period["end_exclusive"].startswith("2026-11-02T00:00:00")
