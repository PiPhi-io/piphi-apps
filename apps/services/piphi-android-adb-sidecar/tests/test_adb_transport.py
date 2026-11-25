from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest

from piphi_android_adb_sidecar.parent_contract_v1 import KeyCode, ReadableProperty
from piphi_android_adb_sidecar.schemas import DeviceConfig
from piphi_android_adb_sidecar.transport import (
    MAX_PROCESS_OUTPUT_BYTES,
    AdbCommandTimeoutError,
    AdbIdentityMismatchError,
    AdbOfflineError,
    AdbOutcomeUnknownError,
    AdbQueueFullError,
    AdbSession,
    AdbTransportError,
    AdbUnauthorizedError,
    BoundedQueue,
    CommandResult,
    SubprocessAdbRunner,
    _drain_bounded,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.serial = "device-serial-1"

    async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
        assert 100 <= timeout_ms <= 30_000
        call = tuple(args)
        self.calls.append(call)
        if call == ("start-server",):
            return CommandResult(0, "", "")
        if call[0] in {"connect", "disconnect"}:
            return CommandResult(0, f"{call[0]}ed", "")
        if call[-1] == "get-state":
            return CommandResult(0, "device", "")
        if call[-2:] == ("getprop", "ro.serialno"):
            return CommandResult(0, self.serial, "")
        if call[-2:] == ("getprop", "ro.boot.serialno"):
            return CommandResult(0, "", "")
        if "getprop" in call:
            return CommandResult(0, f"value-{call[-1]}", "")
        if call[-3:-1] == ("input", "keyevent"):
            return CommandResult(0, "", "")
        raise AssertionError(f"unexpected ADB call: {call}")


def config() -> DeviceConfig:
    return DeviceConfig.model_validate(
        {
            "id": "transport-test",
            "host": "192.0.2.10",
            "port": 5555,
            "queue_capacity": 2,
        }
    )


@pytest.mark.anyio
async def test_session_connects_queries_and_sends_only_allowlisted_key() -> None:
    runner = FakeRunner()
    session = AdbSession(config(), runner=runner)

    await session.open()
    assert session.connected is True
    assert session.authorized is True
    assert session.target_id and session.target_id.startswith("adb-")
    assert session.metadata["ro.product.model"] == "value-ro.product.model"

    values = await session.query_properties(
        [ReadableProperty.PRODUCT_MODEL, ReadableProperty.ANDROID_SDK],
        timeout_ms=1_000,
    )
    assert values == {
        "ro.product.model": "value-ro.product.model",
        "ro.build.version.sdk": "value-ro.build.version.sdk",
    }
    assert await session.send_key(KeyCode.HOME, 2, timeout_ms=1_000) == 2
    assert runner.calls[-2:] == [
        (
            "-s",
            "192.0.2.10:5555",
            "shell",
            "input",
            "keyevent",
            "KEYCODE_HOME",
        ),
        (
            "-s",
            "192.0.2.10:5555",
            "shell",
            "input",
            "keyevent",
            "KEYCODE_HOME",
        ),
    ]
    assert all(";" not in part for call in runner.calls for part in call)


@pytest.mark.anyio
async def test_reconnect_rejects_changed_device_identity() -> None:
    runner = FakeRunner()
    session = AdbSession(config(), runner=runner)
    await session.open()
    original_target = session.target_id
    runner.serial = "different-device"
    with pytest.raises(AdbIdentityMismatchError, match="identity_changed"):
        await session.open()
    assert session.target_id == original_target


@pytest.mark.anyio
async def test_queue_serializes_and_rejects_saturation() -> None:
    queue = BoundedQueue(1)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def blocked() -> str:
        entered.set()
        await release.wait()
        return "done"

    task = asyncio.create_task(queue.submit(blocked))
    await entered.wait()
    with pytest.raises(AdbQueueFullError, match="saturated"):
        await queue.submit(blocked)
    release.set()
    assert await task == "done"
    assert queue.pending == 0
    assert queue.high_water_mark == 1


@pytest.mark.anyio
async def test_open_classifies_connect_authorization_and_identity_failures() -> None:
    class FailureRunner(FakeRunner):
        def __init__(self, failure: str) -> None:
            super().__init__()
            self.failure = failure

        async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
            call = tuple(args)
            if self.failure == "connect" and call[0] == "connect":
                return CommandResult(1, "", "unable to connect")
            if self.failure == "unauthorized" and call[-1] == "get-state":
                return CommandResult(1, "", "device unauthorized")
            if self.failure == "identity" and "getprop" in call:
                return CommandResult(0, "", "")
            return await super().run(args, timeout_ms=timeout_ms)

    with pytest.raises(AdbOfflineError, match="connect_failed"):
        await AdbSession(config(), runner=FailureRunner("connect")).open()
    with pytest.raises(AdbUnauthorizedError, match="unauthorized"):
        await AdbSession(config(), runner=FailureRunner("unauthorized")).open()
    with pytest.raises(AdbIdentityMismatchError, match="identity_unavailable"):
        await AdbSession(config(), runner=FailureRunner("identity")).open()


@pytest.mark.anyio
async def test_property_output_is_bounded_and_offline_access_fails() -> None:
    class OversizedRunner(FakeRunner):
        async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
            result = await super().run(args, timeout_ms=timeout_ms)
            if tuple(args)[-2:] == ("getprop", "ro.product.model"):
                return CommandResult(0, "x" * 257, "")
            return result

    session = AdbSession(config(), runner=FakeRunner())
    with pytest.raises(AdbOfflineError, match="offline"):
        await session.query_properties([ReadableProperty.PRODUCT_MODEL], timeout_ms=500)

    oversized = AdbSession(config(), runner=OversizedRunner())
    with pytest.raises(AdbTransportError, match="output_too_large"):
        await oversized.open()


@pytest.mark.anyio
async def test_failed_or_cancelled_key_event_is_never_replayed() -> None:
    class TimeoutRunner(FakeRunner):
        key_attempts = 0

        async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
            if tuple(args)[-3:-1] == ("input", "keyevent"):
                self.key_attempts += 1
                raise AdbCommandTimeoutError("timeout")
            return await super().run(args, timeout_ms=timeout_ms)

    runner = TimeoutRunner()
    session = AdbSession(config(), runner=runner)
    await session.open()
    with pytest.raises(AdbOutcomeUnknownError, match="outcome_unknown"):
        await session.send_key(KeyCode.HOME, 2, timeout_ms=500)
    assert runner.key_attempts == 1
    assert session.connected is False
    assert session.authorized is False


@pytest.mark.anyio
async def test_subprocess_runner_and_stream_reader_enforce_local_bounds(tmp_path, monkeypatch) -> None:
    with pytest.raises(AdbOfflineError, match="unavailable"):
        await SubprocessAdbRunner(str(tmp_path / "missing-adb")).run(
            ("start-server",), timeout_ms=500
        )

    monkeypatch.setenv("PIPHI_ADB_HOME", str(tmp_path / "home"))
    executable = tmp_path / "adb"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    result = await SubprocessAdbRunner(str(executable)).run(("start-server",), timeout_ms=500)
    assert result.returncode == 0
    android_home = tmp_path / "home" / ".android"
    assert android_home.stat().st_mode & 0o777 == 0o700
    private_key = android_home / "adbkey"
    private_key.write_text("secret")
    SubprocessAdbRunner._secure_credentials(android_home)
    assert private_key.stat().st_mode & 0o777 == 0o600

    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * (MAX_PROCESS_OUTPUT_BYTES + 10))
    reader.feed_eof()
    output, truncated = await _drain_bounded(reader, limit=MAX_PROCESS_OUTPUT_BYTES)
    assert len(output) == MAX_PROCESS_OUTPUT_BYTES
    assert truncated is True
    assert await _drain_bounded(None, limit=1) == (b"", False)


def test_queue_capacity_is_bounded() -> None:
    with pytest.raises(ValueError, match="capacity"):
        BoundedQueue(0)
    with pytest.raises(ValueError, match="capacity"):
        BoundedQueue(101)


@pytest.mark.parametrize("host", ["-a", "host:5555", "bad_name", "::1"])
def test_config_rejects_ambiguous_or_unsupported_hosts(host: str) -> None:
    with pytest.raises(ValueError, match="host|IPv6"):
        DeviceConfig.model_validate({"id": "invalid-host", "host": host})
