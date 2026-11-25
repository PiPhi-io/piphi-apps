from __future__ import annotations

from collections.abc import AsyncIterator
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import rehydrate_runtime_configs, runtime_lifespan

from .gateway import gateway
from .schemas import DeviceConfig
from .state import apply_config, remove_config, registry, runtime


async def startup_sync(runtime_context, client) -> None:
    async def apply_snapshot(snapshot) -> None:
        incoming = {str(config.config_id or config.id): config for config in snapshot.configs}
        if len(incoming) > 1:
            raise ValueError("BLE gateway accepts exactly one service configuration")
        for config_id in list(registry.ids()):
            if config_id not in incoming:
                await remove_config(config_id)
        for config in incoming.values():
            await apply_config(config)
        runtime.process_state.current_generation = snapshot.generation

    await rehydrate_runtime_configs(
        runtime_context=runtime_context,
        client=client,
        apply_snapshot=apply_snapshot,
        config_model=DeviceConfig,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with runtime_lifespan(runtime, on_startup=startup_sync):
        await gateway.start()
        supervisor = asyncio.create_task(gateway.supervise(), name="ble-adapter-supervisor")
        try:
            yield
        finally:
            supervisor.cancel()
            await asyncio.gather(supervisor, return_exceptions=True)
            await gateway.stop()
