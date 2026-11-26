from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from piphi_runtime_kit_python import RuntimeConfigSnapshot

from piphi_android_adb_sidecar import lifecycle
from piphi_android_adb_sidecar.app import create_app
from piphi_android_adb_sidecar.network_policy import is_allowed_local_address
from piphi_android_adb_sidecar.routes import sidecar_api
from piphi_android_adb_sidecar.schemas import DeviceConfig
from piphi_android_adb_sidecar.security import REDACTED, redact
from piphi_android_adb_sidecar.transport import AdbSession, CommandResult

AUTH_HEADERS = {"Authorization": "Bearer hardening-token"}


class FakeRunner:
    def __init__(self, serial: str = "stable-serial") -> None:
        self.serial = serial
        self.calls: list[tuple[str, ...]] = []

    async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
        call = tuple(args)
        self.calls.append(call)
        if call[:1] in {("start-server",), ("connect",), ("disconnect",)}:
            return CommandResult(0, "connected", "")
        if call[-1:] == ("get-state",):
            return CommandResult(0, "device", "")
        if call[-2:] == ("getprop", "ro.serialno"):
            return CommandResult(0, self.serial, "")
        if "getprop" in call:
            return CommandResult(0, "value", "")
        if call[:1] == ("pair",):
            return CommandResult(0, "Successfully paired", "")
        if call == ("mdns", "services"):
            return CommandResult(
                0,
                "adb-example _adb-tls-pairing._tcp. 192.168.1.20:37123\n"
                "ignored _other._tcp. 8.8.8.8:1234",
                "",
            )
        raise AssertionError(call)


@pytest.mark.anyio
async def test_health_only_public_and_pairing_code_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PIPHI_ANDROID_ADB_SIDECAR_TOKEN", "hardening-token")
    runner = FakeRunner()
    monkeypatch.setattr(sidecar_api, "pairing_runner", runner)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/diagnostics")).status_code == 401
        response = await client.post(
            "/v1/adb/pair",
            headers=AUTH_HEADERS,
            json={"host": "192.168.1.20", "port": 37123, "pairing_code": "123456"},
        )
        discovered = await client.get("/v1/adb/mdns", headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "paired"}
    assert "123456" not in response.text
    assert discovered.status_code == 200
    assert discovered.json() == {
        "candidates": [
            {
                "service_type": "_adb-tls-pairing._tcp",
                "host": "192.168.1.20",
                "port": 37123,
                "verification_status": "unverified",
            }
        ]
    }


@pytest.mark.anyio
async def test_adb_identity_is_stable_across_address_changes() -> None:
    first = AdbSession(DeviceConfig(id="tv", host="192.168.1.20"), runner=FakeRunner())
    second = AdbSession(DeviceConfig(id="tv", host="192.168.1.21"), runner=FakeRunner())
    await first.open()
    await second.open()
    assert first.target_id == second.target_id


def test_recursive_redaction_and_local_address_policy() -> None:
    assert redact({"outer": [{"pairing_code": "123456"}], "token": "secret"}) == {
        "outer": [{"pairing_code": REDACTED}],
        "token": REDACTED,
    }
    assert is_allowed_local_address("10.1.2.3") is True
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
