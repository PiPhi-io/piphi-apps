from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan
from piphi_runtime_kit_python import rehydrate_runtime_configs

from .schemas import DeviceConfig
from .state import apply_config_snapshot, restore_runtime_state, runtime, scan_poll_loop


async def startup_sync(runtime_context, client) -> None:
    await restore_runtime_state()

    async def apply_snapshot(snapshot) -> None:
        await apply_config_snapshot(snapshot, restored=True)

    await rehydrate_runtime_configs(
        runtime_context=runtime_context,
        client=client,
        apply_snapshot=apply_snapshot,
        config_model=DeviceConfig,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        task = asyncio.create_task(scan_poll_loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
