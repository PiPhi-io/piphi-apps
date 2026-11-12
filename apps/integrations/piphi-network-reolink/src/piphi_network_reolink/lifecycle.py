from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import close_clients, poll_devices, runtime


async def startup_sync(_runtime, _client) -> None:
    # Real integrations can fetch an existing config snapshot from Core here.
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        poll_task = asyncio.create_task(poll_devices())
        try:
            yield
        finally:
            poll_task.cancel()
            await asyncio.gather(poll_task, return_exceptions=True)
            await close_clients()
