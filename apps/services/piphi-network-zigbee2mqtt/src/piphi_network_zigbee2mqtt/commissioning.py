from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bridge_models import MqttSettings, PermitJoinResponse

PermitJoinCall = Callable[..., Awaitable[PermitJoinResponse]]


class PermitJoinController:
    """Keep commissioning bounded and close it after failure, timeout, or restart."""

    def __init__(self, state_path: str | Path | None = None) -> None:
        self.state_path = Path(
            state_path
            or os.getenv("PIPHI_PERMIT_JOIN_STATE_PATH", "/app/data/permit-join-state.json")
        )
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._completed: dict[str, PermitJoinResponse] = {}

    async def execute(
        self,
        *,
        operation_id: str,
        mqtt: MqttSettings,
        value: bool,
        duration: int,
        device: str | None,
        call: PermitJoinCall,
        dry_run: bool = False,
    ) -> PermitJoinResponse:
        async with self._lock:
            if operation_id in self._completed:
                return self._completed[operation_id]
            if value:
                await self._cancel_and_close(mqtt=mqtt, call=call, device=device, dry_run=dry_run)
            try:
                result = await call(value=value, time=duration, device=device, dry_run=dry_run)
            except Exception:
                if value:
                    with suppress(Exception):
                        await call(value=False, time=1, device=device, dry_run=dry_run)
                raise
            if not result.ok:
                if value:
                    with suppress(Exception):
                        await call(value=False, time=1, device=device, dry_run=dry_run)
                return result
            self._completed[operation_id] = result
            if len(self._completed) > 256:
                self._completed.pop(next(iter(self._completed)))
            if value and not dry_run:
                self._persist_active(operation_id, mqtt.base_topic, device, duration)
                self._task = asyncio.create_task(
                    self._close_after(duration, mqtt=mqtt, call=call, device=device)
                )
            elif not value:
                self._clear_state()
            return result

    async def recover(self, mqtt: MqttSettings, call: PermitJoinCall) -> bool:
        if not self.state_path.exists():
            return False
        with suppress(Exception):
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            device = payload.get("device") if isinstance(payload, dict) else None
            await call(value=False, time=1, device=device, dry_run=False)
            self._clear_state()
            return True
        return False

    async def close(self, mqtt: MqttSettings, call: PermitJoinCall) -> None:
        async with self._lock:
            await self._cancel_and_close(mqtt=mqtt, call=call, device=None, dry_run=False)

    async def _cancel_and_close(
        self,
        *,
        mqtt: MqttSettings,
        call: PermitJoinCall,
        device: str | None,
        dry_run: bool,
    ) -> None:
        task = self._task
        self._task = None
        if task and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self.state_path.exists() and not dry_run:
            await call(value=False, time=1, device=device, dry_run=False)
            self._clear_state()

    async def _close_after(
        self,
        duration: int,
        *,
        mqtt: MqttSettings,
        call: PermitJoinCall,
        device: str | None,
    ) -> None:
        try:
            await asyncio.sleep(duration)
            await call(value=False, time=1, device=device, dry_run=False)
        finally:
            self._clear_state()
            self._task = None

    def _persist_active(
        self, operation_id: str, base_topic: str, device: str | None, duration: int
    ) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "operation_id": operation_id,
            "base_topic": base_topic,
            "device": device,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=duration)).isoformat(),
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.state_path)

    def _clear_state(self) -> None:
        with suppress(FileNotFoundError):
            self.state_path.unlink()


permit_join_controller = PermitJoinController()
