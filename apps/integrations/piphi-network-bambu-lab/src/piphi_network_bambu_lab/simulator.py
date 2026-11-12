"""Opt-in printer simulation that exercises the same report normalization path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


class SimulatedPrinterSession:
    def __init__(
        self,
        *,
        on_report: Callable[[dict[str, Any]], None],
        on_offline: Callable[[], None],
    ) -> None:
        self._on_report = on_report
        self._on_offline = on_offline
        self._task: asyncio.Task[None] | None = None
        self.connected = False
        self.progress = 32

    def start(self) -> None:
        self.connected = True
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        self.connected = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def request_full_status(self) -> bool:
        if not self.connected:
            return False
        self._on_report(self._sample())
        return True

    def _sample(self) -> dict[str, Any]:
        return {"print": {
            "command": "push_status",
            "gcode_state": "RUNNING",
            "mc_percent": self.progress,
            "mc_remaining_time": max(0, round((100 - self.progress) * 1.5)),
            "layer_num": round(self.progress * 2.4),
            "total_layer_num": 240,
            "nozzle_temper": 218.6,
            "nozzle_target_temper": 220,
            "bed_temper": 59.7,
            "bed_target_temper": 60,
        }}

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(0)
                self._on_report(self._sample())
                await asyncio.sleep(5)
                self.progress = 32 if self.progress >= 97 else self.progress + 5
        except asyncio.CancelledError:
            return
