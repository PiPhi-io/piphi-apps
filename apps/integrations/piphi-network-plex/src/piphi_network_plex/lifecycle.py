from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from .schemas import DeviceConfig
from .state import apply_runtime_config_snapshot, plex_service, runtime, starter


async def startup_sync(_runtime, client) -> None:
    await starter.rehydrate_configs(
        client=client,
        apply_snapshot=apply_runtime_config_snapshot,
        config_model=DeviceConfig,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        try:
            yield
        finally:
            await plex_service.close()
