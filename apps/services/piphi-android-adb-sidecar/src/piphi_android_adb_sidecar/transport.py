from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from .parent_contract_v1 import KeyCode, ReadableProperty
from .schemas import DeviceConfig

T = TypeVar("T")
MAX_PROCESS_OUTPUT_BYTES = 8_192
MAX_PROPERTY_VALUE_BYTES = 256

KEY_EVENT_NAMES: dict[KeyCode, str] = {
    KeyCode.BACK: "KEYCODE_BACK",
    KeyCode.HOME: "KEYCODE_HOME",
    KeyCode.ENTER: "KEYCODE_ENTER",
    KeyCode.DPAD_UP: "KEYCODE_DPAD_UP",
    KeyCode.DPAD_DOWN: "KEYCODE_DPAD_DOWN",
    KeyCode.DPAD_LEFT: "KEYCODE_DPAD_LEFT",
    KeyCode.DPAD_RIGHT: "KEYCODE_DPAD_RIGHT",
    KeyCode.VOLUME_UP: "KEYCODE_VOLUME_UP",
    KeyCode.VOLUME_DOWN: "KEYCODE_VOLUME_DOWN",
    KeyCode.VOLUME_MUTE: "KEYCODE_VOLUME_MUTE",
    KeyCode.MEDIA_PLAY_PAUSE: "KEYCODE_MEDIA_PLAY_PAUSE",
}


class AdbTransportError(RuntimeError):
    """Base class for sanitized ADB transport failures."""


class AdbOfflineError(AdbTransportError):
    pass


class AdbUnauthorizedError(AdbTransportError):
    pass


class AdbIdentityMismatchError(AdbTransportError):
    pass


class AdbCommandTimeoutError(AdbTransportError):
    pass


class AdbQueueFullError(AdbTransportError):
    pass


class AdbOutcomeUnknownError(AdbTransportError):
    pass


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    output_truncated: bool = False


class CommandRunner(Protocol):
    async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult: ...


async def _drain_bounded(
    stream: asyncio.StreamReader | None,
    *,
    limit: int,
) -> tuple[bytes, bool]:
    if stream is None:
        return b"", False
    retained = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(4_096)
        if not chunk:
            break
        remaining = max(0, limit - len(retained))
        retained.extend(chunk[:remaining])
        truncated = truncated or len(chunk) > remaining
    return bytes(retained), truncated


class SubprocessAdbRunner:
    """Run a private Platform Tools client without a shell or unbounded output."""

    def __init__(self, executable: str | None = None) -> None:
        self.executable = str(
            executable or os.getenv("PIPHI_ADB_BINARY", "/usr/bin/adb")
        )
        self.home = Path(os.getenv("PIPHI_ADB_HOME", "/app/data"))

    async def run(self, args: Sequence[str], *, timeout_ms: int) -> CommandResult:
        if not Path(self.executable).is_file():
            raise AdbOfflineError("adb_unavailable")
        if args == ("start-server",):
            private_key = self.home / ".android" / "adbkey"
            public_key = self.home / ".android" / "adbkey.pub"
            if not private_key.is_file() or not public_key.is_file():
                raise AdbUnauthorizedError("adb_authorized_keys_unavailable")
        environment = os.environ.copy()
        environment["HOME"] = str(self.home)
        environment["ADB_VENDOR_KEYS"] = str(self.home / ".android" / "adbkey")
        process = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        stdout_task = asyncio.create_task(
            _drain_bounded(process.stdout, limit=MAX_PROCESS_OUTPUT_BYTES)
        )
        stderr_task = asyncio.create_task(
            _drain_bounded(process.stderr, limit=MAX_PROCESS_OUTPUT_BYTES)
        )
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                returncode = await process.wait()
        except (TimeoutError, asyncio.CancelledError) as exc:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise AdbCommandTimeoutError("adb_command_timeout") from exc
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        stdout_bytes, stdout_truncated = stdout
        stderr_bytes, stderr_truncated = stderr
        return CommandResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace").strip(),
            stderr=stderr_bytes.decode("utf-8", errors="replace").strip(),
            output_truncated=stdout_truncated or stderr_truncated,
        )


class BoundedQueue:
    def __init__(self, capacity: int) -> None:
        if not 1 <= capacity <= 100:
            raise ValueError("queue capacity must be between 1 and 100")
        self.capacity = capacity
        self.pending = 0
        self.high_water_mark = 0
        self._lock = asyncio.Lock()

    async def submit(self, operation: Callable[[], Awaitable[T]]) -> T:
        if self.pending >= self.capacity:
            raise AdbQueueFullError("command_queue_saturated")
        self.pending += 1
        self.high_water_mark = max(self.high_water_mark, self.pending)
        try:
            return await self.run_exclusive(operation)
        finally:
            self.pending -= 1

    async def run_exclusive(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            return await operation()


class AdbSession:
    """Exclusive bounded owner of one configured network ADB target."""

    def __init__(self, config: DeviceConfig, runner: CommandRunner | None = None) -> None:
        self.config = config
        self.runner = runner or SubprocessAdbRunner()
        self.queue = BoundedQueue(config.queue_capacity)
        self.endpoint = f"{config.host}:{config.port}"
        self.connected = False
        self.authorized = False
        self.target_id: str | None = None
        self.metadata: dict[str, str] = {}
        self._identity_digest: str | None = None

    async def open(self) -> None:
        self.connected = False
        self.authorized = False
        await self._require_success(
            await self.runner.run(
                ("start-server",), timeout_ms=self.config.connect_timeout_ms
            )
        )
        connected = await self.runner.run(
            ("connect", self.endpoint), timeout_ms=self.config.connect_timeout_ms
        )
        combined = f"{connected.stdout}\n{connected.stderr}".lower()
        if connected.returncode != 0 or "failed" in combined or "unable" in combined:
            raise AdbOfflineError("adb_connect_failed")
        state = await self.runner.run(
            ("-s", self.endpoint, "get-state"),
            timeout_ms=self.config.connect_timeout_ms,
        )
        state_text = f"{state.stdout}\n{state.stderr}".lower()
        if "unauthorized" in state_text:
            raise AdbUnauthorizedError("adb_target_unauthorized")
        if state.returncode != 0 or state.stdout.strip() != "device":
            raise AdbOfflineError("adb_target_offline")

        identity = await self._query_internal_identity()
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        if self._identity_digest is not None and digest != self._identity_digest:
            raise AdbIdentityMismatchError("adb_target_identity_changed")
        self._identity_digest = digest
        if self.target_id is None:
            self.target_id = f"adb-{secrets.token_urlsafe(24)}"
        self.metadata = await self._query_properties(list(ReadableProperty))
        self.connected = True
        self.authorized = True

    async def close(self) -> None:
        self.connected = False
        self.authorized = False
        try:
            await self.runner.run(
                ("disconnect", self.endpoint),
                timeout_ms=self.config.connect_timeout_ms,
            )
        except (AdbTransportError, OSError):
            pass

    async def query_properties(
        self,
        properties: list[ReadableProperty],
        *,
        timeout_ms: int,
    ) -> dict[str, str]:
        self._require_connected()

        async def operation() -> dict[str, str]:
            return await self._query_properties(properties, timeout_ms=timeout_ms)

        return await self._submit(operation, timeout_ms=timeout_ms)

    async def send_key(
        self,
        key: KeyCode,
        repeat: int,
        *,
        timeout_ms: int,
    ) -> int:
        self._require_connected()

        async def operation() -> int:
            completed = 0
            for _ in range(repeat):
                try:
                    result = await self.runner.run(
                        (
                            "-s",
                            self.endpoint,
                            "shell",
                            "input",
                            "keyevent",
                            KEY_EVENT_NAMES[key],
                        ),
                        timeout_ms=timeout_ms,
                    )
                    await self._require_success(result)
                except (AdbTransportError, OSError, asyncio.CancelledError) as exc:
                    self.connected = False
                    self.authorized = False
                    raise AdbOutcomeUnknownError("key_event_outcome_unknown") from exc
                completed += 1
            return completed

        return await self._submit(operation, timeout_ms=timeout_ms)

    async def _submit(self, operation: Callable[[], Awaitable[T]], *, timeout_ms: int) -> T:
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                return await self.queue.submit(operation)
        except TimeoutError as exc:
            raise AdbCommandTimeoutError("adb_request_timeout") from exc

    async def _query_internal_identity(self) -> str:
        values: list[str] = []
        for property_name in ("ro.serialno", "ro.boot.serialno"):
            result = await self.runner.run(
                ("-s", self.endpoint, "shell", "getprop", property_name),
                timeout_ms=self.config.connect_timeout_ms,
            )
            await self._require_success(result)
            if result.stdout.strip():
                values.append(result.stdout.strip())
                break
        if not values:
            raise AdbIdentityMismatchError("adb_target_identity_unavailable")
        values.extend((self.config.host, str(self.config.port)))
        return "\0".join(values)

    async def _query_properties(
        self,
        properties: list[ReadableProperty],
        *,
        timeout_ms: int | None = None,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        command_timeout = timeout_ms or self.config.operation_timeout_ms
        for property_name in properties:
            command = await self.runner.run(
                ("-s", self.endpoint, "shell", "getprop", property_name.value),
                timeout_ms=command_timeout,
            )
            await self._require_success(command)
            encoded = command.stdout.encode("utf-8")
            if command.output_truncated or len(encoded) > MAX_PROPERTY_VALUE_BYTES:
                raise AdbTransportError("adb_property_output_too_large")
            if "\n" in command.stdout or "\r" in command.stdout:
                raise AdbTransportError("adb_property_output_invalid")
            result[property_name.value] = command.stdout
        return result

    async def _require_success(self, result: CommandResult) -> None:
        if result.returncode == 0 and not result.output_truncated:
            return
        combined = f"{result.stdout}\n{result.stderr}".lower()
        if "unauthorized" in combined:
            raise AdbUnauthorizedError("adb_target_unauthorized")
        if "offline" in combined or "no devices" in combined or "not found" in combined:
            self.connected = False
            raise AdbOfflineError("adb_target_offline")
        raise AdbTransportError("adb_command_failed")

    def _require_connected(self) -> None:
        if not self.connected:
            raise AdbOfflineError("adb_target_offline")
