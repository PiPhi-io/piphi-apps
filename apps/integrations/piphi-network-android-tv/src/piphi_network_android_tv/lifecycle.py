from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import android_tv_service, pairing_manager, runtime


async def startup_sync(_runtime, _client) -> None:
    # Real integrations can fetch an existing config snapshot from Core here.
    return None


async def cleanup_expired_pairings() -> None:
    while True:
        await asyncio.sleep(15)
        await pairing_manager.cleanup()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        cleanup_task = asyncio.create_task(
            cleanup_expired_pairings(),
            name="android-tv-pairing-cleanup",
        )
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
            await pairing_manager.close()
            await android_tv_service.close()
