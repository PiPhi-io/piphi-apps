from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import refresh_all_entries, runtime


async def startup_sync(_runtime, _client) -> None:
    # Real integrations can fetch an existing config snapshot from Core here.
    return None


async def availability_loop() -> None:
    while True:
        loop = asyncio.get_running_loop()
        cycle_started = loop.time()
        await refresh_all_entries()
        elapsed = loop.time() - cycle_started
        await asyncio.sleep(max(0.0, _probe_interval_seconds() - elapsed))


def _probe_interval_seconds() -> float:
    try:
        return max(
            5.0,
            min(float(os.getenv("PIPHI_CAMERA_PROBE_INTERVAL_SECONDS", "15")), 300.0),
        )
    except ValueError:
        return 15.0


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        probe_task = asyncio.create_task(
            availability_loop(), name="camera-availability-probe"
        )
        try:
            yield
        finally:
            probe_task.cancel()
            with suppress(asyncio.CancelledError):
                await probe_task
