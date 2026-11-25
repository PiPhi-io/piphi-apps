from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from piphi_runtime_kit_python import (
    RuntimeConfig,
    rehydrate_runtime_configs,
    runtime_lifespan,
)

from .schemas import DeviceConfig
from .state import (
    android_tv_service,
    apply_config,
    config_sync,
    pairing_manager,
    registry,
    remove_config,
    runtime,
)


async def _apply_rehydrated_config(config: RuntimeConfig) -> None:
    await apply_config(DeviceConfig.model_validate(config.model_dump()))


async def startup_sync(runtime_context, client) -> None:
    async def apply_snapshot(snapshot) -> None:
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
