from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .state import runtime


async def startup_sync(_runtime, _client) -> None:
    # Real integrations can fetch an existing config snapshot from Core here.
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        yield
