from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import restore_persisted_configs, runtime, shutdown_supervisors


async def startup_sync(_runtime, _client) -> None:
    await restore_persisted_configs()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        try:
            yield
        finally:
            await shutdown_supervisors()
