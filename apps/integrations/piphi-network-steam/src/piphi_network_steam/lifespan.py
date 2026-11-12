from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from piphi_runtime_kit_python import runtime_lifespan

from . import runtime as runtime_module


async def startup_sync(_runtime_context, core_http_client) -> None:
    await runtime_module.starter.rehydrate_configs(
        client=core_http_client,
        apply_snapshot=runtime_module.apply_runtime_config_snapshot,
        config_model=runtime_module.SteamConfig,
        snapshot_model=runtime_module.RuntimeConfigSnapshot,
        timeout_seconds=10.0,
    )


async def shutdown_sync(_runtime_context) -> None:
    try:
        await runtime_module.steam_client.aclose()
    finally:
        await runtime_module.reset_runtime_state()


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    async with runtime_lifespan(
        runtime_module.runtime,
        on_startup=startup_sync,
        on_shutdown=shutdown_sync,
        core_client_timeout_seconds=10.0,
    ):
        yield
