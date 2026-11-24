from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from piphi_runtime_kit_python import rehydrate_runtime_configs, runtime_lifespan

from .schemas import DeviceConfig
from .state import (
    apply_config_snapshot,
    poll_access_points,
    restore_runtime_state,
    runtime,
)


async def startup_sync(runtime_context: Any, client: Any) -> None:
    async def apply_snapshot(snapshot: Any) -> None:
        await apply_config_snapshot(
            snapshot,
            restored=True,
            allow_unavailable=True,
        )

    await restore_runtime_state()
    await rehydrate_runtime_configs(
        runtime_context=runtime_context,
        client=client,
        apply_snapshot=apply_snapshot,
        config_model=DeviceConfig,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        task = asyncio.create_task(poll_access_points())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
