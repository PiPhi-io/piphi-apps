from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from piphi_runtime_kit_python import RuntimeConfig, rehydrate_runtime_configs, runtime_lifespan

from .schemas import DeviceConfig
from .state import apply_config, config_sync, poll_access_points, registry, remove_config, runtime


async def _apply_rehydrated_config(config: RuntimeConfig) -> None:
    await apply_config(
        DeviceConfig.model_validate(config.model_dump()),
        restored=True,
        allow_unavailable=True,
    )


async def startup_sync(runtime_context: Any, client: Any) -> None:
    async def apply_snapshot(snapshot: Any) -> None:
        await config_sync.apply_snapshot(
            snapshot=snapshot,
            active_config_ids=registry.ids(),
            apply_config=_apply_rehydrated_config,
            remove_config=remove_config,
            get_active_config_ids=registry.ids,
        )

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
